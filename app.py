"""
這個程式是根據 https://github.com/Bamorph/Meshtastic_MQTT_Terminal/blob/main/main.py 改編而來。

原始碼版權歸原作者所有。
"""
#!/usr/bin/env python3
import logging
import os
import base64
import asyncio
import paho.mqtt.client as mqtt

from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2, BROADCAST_NUM

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# from plyer import notification

from dotenv import load_dotenv
from telegram import Bot

import sqlite3

# 加載 .env 文件
load_dotenv()

# 從環境變數中獲取 token
TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 建立 Telegram Bot 物件
bot = Bot(token=TOKEN)

# Default settings
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

root_topic = os.getenv("MQTT_ROOT_TOPIC")
channel = os.getenv("MQTT_CHANNEL")
key = os.getenv("MQTT_MESH_KEY")

padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')
replaced_key = padded_key.replace('-', '+').replace('_', '/')
key = replaced_key

# Convert hex to int and remove '!'
# node_number = int('abcd', 16)

async def send_telegram_message(bot, chat_id, text_payload):
    await bot.send_message(chat_id=chat_id, text=text_payload, parse_mode='MarkdownV2')

def process_message(mp, text_payload, is_encrypted):

    text = {
        "message": text_payload,
        "from": getattr(mp, "from"),
        "id": getattr(mp, "id"),
        "to": getattr(mp, "to")
    }

    # notification.notify(
    # title = f"{getattr(mp, 'from')}",
    # message = f"{text_payload}",
    # timeout = 10
    # )
    print(text)

def decode_encrypted(message_packet, client_id):
    try:
        key_bytes = base64.b64decode(key.encode('ascii'))

        nonce_packet_id = getattr(message_packet, "id").to_bytes(8, "little")
        nonce_from_node = getattr(message_packet, "from").to_bytes(8, "little")
        nonce = nonce_packet_id + nonce_from_node

        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(message_packet, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        message_packet.decoded.CopyFrom(data)

        if message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            is_encrypted = True
            # 目前不需要另外再包裝一層，所以就不丟出去process
            # process_message(message_packet, text_payload, is_encrypted)
            # print(f"{text_payload}")
            return text_payload


        elif message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
                info = mesh_pb2.User()
                info.ParseFromString(message_packet.decoded.payload)

                if info.long_name is not None:
                    print('----->nodeinfo',info)
                    print(f'id:{info.id}, long_name:{info.long_name}')
                    # 建立或連接到數據庫
                    conn = sqlite3.connect('meshtastic.db')
                    cursor = conn.cursor()

                    # 檢查是否存在該行
                    cursor.execute(f'SELECT * FROM {channel} WHERE client_id = ?', (client_id,))
                    existing_row = cursor.fetchone()

                    # 如果該行存在，執行更新操作；否則執行插入操作
                    if existing_row:
                        cursor.execute(f'''UPDATE {channel} SET
                                        long_name = ?, short_name = ?
                                        WHERE client_id = ?''',
                                    (info.long_name, info.short_name, client_id))
                    else:
                        cursor.execute(f'''INSERT INTO {channel}
                                        (client_id, long_name, short_name)
                                        VALUES (?, ?, ?, ?, ?, ?)''',
                                    (client_id, info.long_name, info.short_name))

                    # 確認並提交更改
                    conn.commit()

                    # 關閉連接
                    conn.close()


                # notification.notify(
                # title = "Meshtastic",
                # message = f"{info}",
                # timeout = 10
                # )
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)

            if pos.latitude_i != 0:
                # print('----->client_id',client_id)
                print('----->pos',pos)
                # # 建立或連接到數據庫
                conn = sqlite3.connect('meshtastic.db')
                cursor = conn.cursor()

                # 檢查是否存在該行
                cursor.execute(f'SELECT * FROM {channel} WHERE client_id = ?', (client_id,))
                existing_row = cursor.fetchone()

                # 如果該行存在，執行更新操作；否則執行插入操作
                if existing_row:
                    cursor.execute(f'''UPDATE {channel} SET
                                    latitude_i = ?, longitude_i = ?, precision_bits = ?
                                    WHERE client_id = ?''',
                                (pos.latitude_i, pos.longitude_i, pos.precision_bits, client_id))
                else:
                    cursor.execute(f'''INSERT INTO {channel}
                                    (client_id, latitude_i, longitude_i, precision_bits)
                                    VALUES (?, ?, ?, ?)''',
                                (client_id, pos.latitude_i, pos.longitude_i, pos.precision_bits))

                # # 確認並提交更改
                conn.commit()

                # # 關閉連接
                conn.close()
                pass

        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            print('----->env',env)

    except Exception as e:
        print(f"Decryption failed: {str(e)}")

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"Connected to {MQTT_BROKER} on topic:{subscribe_topic} id:{BROADCAST_NUM} send to telegram:{TELEGRAM_CHAT_ID}")
    else:
        print(f"Failed to connect to MQTT broker with result code {str(rc)}")

def on_message(client, userdata, msg):
    service_envelope = mqtt_pb2.ServiceEnvelope()
    try:
        service_envelope.ParseFromString(msg.payload)
        # print('----------->service_envelope',service_envelope)
        message_packet = service_envelope.packet
        # print('----------->message_packet',message_packet)
    except Exception as e:
        print(f"Error parsing message_packet: {str(e)}")
        return

    # 只給特定 channel 的訊息才處理
    if (message_packet.to == BROADCAST_NUM):
        # print(message_packet.to)

        # 獲取發出訊息的 client_id
        topic_parts = msg.topic.split('/')
        if len(topic_parts) >= 3:
            client_id = topic_parts[-1]
            print("Message sent by client_id:", client_id)
        else:
            print("Unable to determine client_id from topic:", msg.topic)

        # 有無加密欄位的不同處理
        if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
            text_payload = decode_encrypted(message_packet, client_id)
            print("----------------------------------*****has decode*****",text_payload)
        else:
            # text_payload = message_packet.decoded.payload.decode("utf-8")
            print("----------------------------------*****no decode*****",mesh_pb2.Data())

        try:
            print(f'client_id:{client_id} , text_payload: {text_payload}')
            # 過濾掉沒有文字內容的行為，像是追蹤NODE、要求位置等
            if text_payload is not None:
                long_name = get_long_name(client_id)
                text_payload = escape_special_characters(text_payload)
                client_id = escape_special_characters(client_id)
                if long_name is not None:
                    long_name = escape_special_characters(long_name)
                    print(f"The long name of client {client_id} is: {long_name}")
                    # msg_with_clientid = f"*{long_name}*\({client_id}\):>{text_payload}"
                    msg_who = f"*{long_name} \({client_id}\)*:"
                    msg_content = f"```\n{text_payload}```"
                else:
                    print(f"No long name found for client {client_id}")
                    # msg_with_clientid = f"*{client_id}*: > {text_payload}"
                    msg_who = f"*{client_id}*:"
                    msg_content = f"```\n{text_payload}```"

                # 將 MQTT 收到的訊息發送到 Telegram
                # asyncio.get_event_loop().run_until_complete(send_telegram_message(bot, TELEGRAM_CHAT_ID, msg_with_clientid))
                asyncio.get_event_loop().run_until_complete(send_telegram_message(bot, TELEGRAM_CHAT_ID, msg_who+msg_content))
            else:
                print("Received None payload. Ignoring...")
        except Exception as e:
            print(f"Error decode_encrypted message: {str(e)}")
            return

def get_long_name(client_id):
    # 連接到 SQLite 資料庫
    conn = sqlite3.connect('meshtastic.db')
    cursor = conn.cursor()

    # 執行 SQL 查詢，從 clients 表中讀取 long name
    cursor.execute("SELECT long_name FROM MeshTW WHERE client_id = ?", (client_id,))
    row = cursor.fetchone()  # 獲取查詢結果的第一行

    # 關閉資料庫連接
    cursor.close()
    conn.close()

    # 如果找到了符合條件的記錄，返回 long name；否則返回 None
    if row:
        return row[0]
    else:
        return None

def escape_special_characters(text):
    special_characters = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    escaped_text = ''
    for char in text:
        if char in special_characters:
            escaped_text += '\\' + char
        else:
            escaped_text += char
    return escaped_text

# 建立或連接到數據庫
conn = sqlite3.connect('meshtastic.db')
cursor = conn.cursor()

# 創建表格
create_table_query = f'''CREATE TABLE IF NOT EXISTS MeshTW (
                            client_id TEXT PRIMARY KEY NOT NULL,
                            long_name TEXT,
                            short_name TEXT,
                            macaddr TEXT,
                            latitude_i TEXT,
                            longitude_i TEXT,
                            altitude TEXT,
                            precision_bits TEXT,
                            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )'''

cursor.execute(create_table_query)

# 確認並提交更改
conn.commit()

# 關閉連接
conn.close()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.on_connect = on_connect
client.username_pw_set(username=MQTT_USERNAME, password=MQTT_PASSWORD)
client.connect(MQTT_BROKER, MQTT_PORT, 60)

subscribe_topic = f"{root_topic}{channel}/#"
client.subscribe(subscribe_topic, 0)

if __name__ == '__main__':
    while client.loop() == 0:
        pass