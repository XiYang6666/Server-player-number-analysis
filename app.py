import time
import sqlite3
import threading
import socket
import smtplib
import email.mime.text
import email.utils
import logging

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response, RedirectResponse
import uvicorn
import yaml


class Email:
    """
    发送邮件
    """

    def __init__(self, smtp_addr: tuple[str, int], user_name: str, password: str, email_addr: str, name=None):
        """
        初始化

        parameters
        --------
        smtp_addr: smtp服务器的地址和端口
        user_name: 登录smtp服务器的用户名
        password: 登录smtp服务器的密码
        email_addr: 你的邮箱地址,用于显示邮件的From
        name: 你的名称,用于显示邮件的From
        """
        self.smtp_connection = smtplib.SMTP()

        self.smtp_addr = smtp_addr
        self.user = user_name
        self.password = password
        self.email_addr = email_addr
        self.name = name

    def send_mail(self, message: str, receivers: list[str]) -> bool:
        """
        发送邮件

        Parameters
        --------
        message: .eml数据(可以用email库生成)
        receivers: 接收邮箱列表
        """
        for i in range(3):
            try:
                self.smtp_connection.connect(*self.smtp_addr)
                self.smtp_connection.login(self.user, self.password)
                self.smtp_connection.sendmail(
                    self.email_addr, receivers, message)
                self.smtp_connection.quit()
            except:
                pass
            else:
                return True
        else:
            return False

    def send_html_file(self, filepath: str, receivers: list, subject: str, format={},):
        """
        读取html文件 替换文件中的花括号并发送邮件

        Parameters
        --------
        filepath: 文件路径
        """
        with open(f"{filepath}", "r", encoding="utf-8") as f:
            html_data = f.read().format(**format)
        email_data = email.mime.text.MIMEText(html_data, "html", "utf-8")
        email_data["From"] = email.utils.formataddr((self.name,self.email_addr))
        email_data["To"] = email.utils.formataddr((None, receivers[0]))
        email_data["Subject"] = subject

        return self.send_mail(email_data.as_string(), receivers)


class Timer(threading.Thread):
    """
    计时器
    指定时间执行一次某函数
    """

    def __init__(self, precision: float):
        """
        初始化计时器

        Parameters
        --------
        precision: 时间精度(秒) 多少秒检测一次
        """
        super().__init__()
        self.precision = precision
        self.timeout_plan = []
        self.interval_plan = []
        self.start()

    def SetTimeout(self, func, timeout):
        """
        新建超时计时器

        到达指定时间后执行函数
        """
        self.timeout_plan.append({
            "function": func,
            "timeout": timeout,
            "start_time": time.time()
        })

    def SetInterval(self, func, timeout):
        """
        新建循环计时器

        每隔一段指定时间执行一次函数
        """
        self.interval_plan.append({
            "function": func,
            "timeout": timeout,
            "last_time": time.time()
        })

    def run(self):
        while True:
            for i in self.timeout_plan:
                if time.time() - i["start_time"] >= i["timeout"]:
                    i["function"]()
            for i in self.interval_plan:
                if time.time() - i["last_time"] >= i["timeout"]:
                    i["last_time"] += i["timeout"]
                    i["function"]()
            time.sleep(self.precision)


class GetServerData:
    """
    获取服务器数据并记录
    """

    def __init__(self, server_addr: tuple, database_path="database.db"):
        self.db_connection = sqlite3.connect(database_path, check_same_thread=False)
        self.db_cursor = self.db_connection.cursor()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(10)
        self.server_addr = server_addr

        with self.db_connection:
            self.db_cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quantity (
                    start_time   REAL     ,
                    end_time     REAL     ,
                    count        INTEGER  ,
                    PRIMARY KEY (start_time)
                )
                """
            )

            # 开始时创建一条占位纪录 防止直接更改上次运行时的记录
            self.db_cursor.execute(
                """
                INSERT INTO quantity(
                        start_time,
                        end_time,
                        count
                    )
                VALUES (
                        :time,
                        :time,
                        -1
                    )
                """, {"time": time.time()}
            )


    def get_data(self) -> dict | bool:
        """
        获取服务器数据
        """
        try:
            start_time = time.time()
            # 数据是抓包抓的 我也不知道这串数据啥意思
            self.socket.sendto(bytes.fromhex("01000000000000233300FFFF00FEFEFEFEFDFDFDFD123456788CE58BDE74FC40EB"), self.server_addr)

            # 也是抓包分析的 只能看懂数据后半段
            data_temp = self.socket.recv(1024)
            ping = time.time() - start_time
            # print(ping)

            data_temp = data_temp[35:].split(b";")

            data = {
                "version": {
                    "name": data_temp[0].decode(),
                    "protocol": data_temp[2].decode()
                },
                "players": {
                    "max": int(data_temp[5].decode()),
                    "online": int(data_temp[4].decode())
                },
                "description": data_temp[1].decode(),
                "gamemode": data_temp[8].decode(),
                "ping": ping
            }
            return data
        except:
            logging.warning("获取服务器数据失败")
            return False

    def record(self):
        """
        获取数据并存到数据库
        """
        # 获取一次数据
        data = self.get_data()
        now_time = time.time()

        with self.db_connection:
            if not data:
                logging.warning("因为无法获取服务器数据 所以未能记录数据")
                # 插入值为-1的数据占位
                player_number = -1
            else:
                player_number = data["players"]["online"]

            self.db_cursor.execute(
                """
                SELECT max(start_time),
                    count
                FROM quantity
                """
            )
            db_data = self.db_cursor.fetchall()
            self.db_cursor.execute(
                    """
                    UPDATE quantity
                    SET end_time = :end_time
                    WHERE start_time=:start_time
                    """, {"start_time":db_data[0][0],"end_time": now_time}
                )
            if db_data[0][1] == player_number:
                # 用户数相同 只更新最新的一条记录的end_time
                pass
            else:
                # 用户数变化 更新最新一条并且再创建一条记录
                self.db_cursor.execute(
                    """
                    INSERT INTO quantity(
                            start_time,
                            end_time,
                            count
                        )
                    VALUES (
                            :time,
                            :time,
                            :count
                        )
                    """, {"time": now_time, "count": player_number}
                )

        return data


    def get_record_data(self,start_time,end_time):
        """
        获取记录的时间段
        """
        with self.db_connection:
            self.db_cursor.execute(
                """
                SELECT *
                FROM quantity
                WHERE (start_time >= :start_time AND start_time <= :end_time)
                    OR (end_time >= :start_time AND end_time <= :end_time)
                """ ,{"start_time": start_time, "end_time": end_time}
            )
            data = self.db_cursor.fetchall()
            ls = []
            for i in data:
                if i[2] < 0:
                    # 不返回值为-1的占位记录
                    continue
                ls.append({
                    "start_time": i[0],
                    "end_time": i[1],
                    "count": i[2]
                })
            return ls


with open("config.yml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f.read())
app = FastAPI()
getServerData = GetServerData((config["detected_server"]["host"], config["detected_server"]["port"]))
timer = Timer(1)
is_send_email = True

def func():
    global is_send_email
    data = getServerData.record()
    if data["players"]["online"] >= config["email"]["target"]:
        if is_send_email and config["email"]["enable"]:
            mail.send_html_file("email.html", config["email"]["receivers"], f"服务器人数达到 {data['players']['online']}人")
            is_send_email = False
    else:
        is_send_email = True


timer.SetInterval(func,60)
mail = Email(
    (config["email"]["smtp"]["host"], config["email"]["smtp"]["port"]),
    config["email"]["smtp"]["user_name"],
    config["email"]["smtp"]["password"],
    config["email"]["email"],
    config["email"]["name"]
)

@app.get("/get_data")
async def get_data(start_time = Query(), end_time = Query()):
    return JSONResponse(
        getServerData.get_record_data(start_time, end_time)
    )


@app.get("/")
async def index():
    return RedirectResponse("/index.html")



app.mount("/", StaticFiles(directory="static"))


if __name__ == "__main__":
    uvicorn.run(app, host=config["server"]["host"], port=config["server"]["port"])
