# storage.py
import threading
import requests
import json
from queue import Queue, Empty

# 创建一个线程安全的队列用于存储待发送的数据
storage_queue = Queue()

# 配置Spring Boot服务器的URL
SPRING_BOOT_URL = 'http://your-spring-boot-server.com:8081/api/store-data'  # 替换为您的实际URL和端口

def storage_worker():
    """
    存储线程的工作函数，持续监听storage_queue并发送数据到Spring Boot服务器。
    """
    while True:
        try:
            # 从队列中获取数据，阻塞等待新数据
            data = storage_queue.get(timeout=5)  # 可根据需要调整超时时间
            if data is None:
                # 如果接收到None，表示需要停止线程
                print("Storage thread received shutdown signal.")
                break

            # 发送POST请求到Spring Boot服务器
            headers = {'Content-Type': 'application/json'}
            response = requests.post(SPRING_BOOT_URL, headers=headers, data=json.dumps(data))

            if response.status_code == 200:
                print(f"Data successfully sent to storage: {data}")
            else:
                print(f"Failed to send data to storage. Status Code: {response.status_code}, Response: {response.text}")

        except Empty:
            # 队列为空，继续等待
            continue
        except Exception as e:
            print(f"An error occurred while sending data to storage: {e}")
        finally:
            storage_queue.task_done()

# 启动存储线程
storage_thread = threading.Thread(target=storage_worker, daemon=True)
storage_thread.start()

def send_to_storage(data):
    """
    将数据放入storage_queue，由storage_worker线程处理发送。
    :param data: 要发送的数据，应该是可序列化为JSON的字典。
    """
    storage_queue.put(data)
