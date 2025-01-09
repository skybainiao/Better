import subprocess
import platform
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import asyncio
import uvicorn

app = FastAPI(title="Ping测试API", description="用于测试指定IP地址的Ping值", version="1.0.0")

# 定义要测试的IP地址列表
DEFAULT_HOSTS = [
    "205.201.2.97",
    "61.14.172.140",
    "66.133.91.108",
    "123.108.119.118",
    "123.108.119.169",
    "123.108.119.24",
    "125.252.69.207",
    "205.201.2.228",
    "125.252.69.206"
]

class PingResult(BaseModel):
    ip: str
    average_ping_ms: Optional[float]
    status: str

class PingRequest(BaseModel):
    command: str  # 客户端发送的命令，例如 "start_ping"

def ping_host(host: str, count: int = 4) -> PingResult:
    """
    Pings a host and returns the average ping time in ms.
    If the host is unreachable, returns status as '失败'.
    """
    system = platform.system().lower()
    param = '-n' if system == 'windows' else '-c'
    command = ['ping', param, str(count), host]

    try:
        # Execute the ping command
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True)
        print(f"Ping Output for {host}:\n{output}")  # 添加日志

        # Parse the output for average time
        if system == 'windows':
            # Windows ping output parsing (中文和英文)
            match = re.search(r'平均\s*=\s*(\d+\.?\d*)ms', output)
            if not match:
                match = re.search(r'Average\s*=\s*(\d+\.?\d*)ms', output)  # 英文系统备选
        else:
            # Unix/Linux/Mac ping output parsing
            match = re.search(r'=\s+([\d\.]+)/([\d\.]+)/([\d\.]+)', output)
            if not match:
                match = re.search(r'=\s+([\d\.]+)\/', output)

        if match:
            avg_ping = float(match.group(1))
            return PingResult(ip=host, average_ping_ms=avg_ping, status="成功")
        else:
            return PingResult(ip=host, average_ping_ms=None, status="失败")
    except subprocess.CalledProcessError as e:
        print(f"Ping failed for {host}: {e.output}")  # 添加日志
        return PingResult(ip=host, average_ping_ms=None, status="失败")

@app.post("/ping", response_model=List[PingResult])
async def ping_api(request: PingRequest):
    """
    API 端点，用于启动Ping测试。
    """
    if request.command != "start_ping":
        raise HTTPException(status_code=400, detail="Invalid command")

    hosts = DEFAULT_HOSTS
    count = 4  # 默认发送4个Ping包

    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(None, ping_host, host, count) for host in hosts]

    results = await asyncio.gather(*tasks)
    return results

@app.get("/")
def read_root():
    return {"message": "欢迎使用 Ping 测试 API！访问 /docs 查看API文档。"}

if __name__ == "__main__":
    uvicorn.run("ping_api:app", host="0.0.0.0", port=8888, reload=True)
