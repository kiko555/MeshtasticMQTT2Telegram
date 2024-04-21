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

from meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, telemetry_pb2

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

# from plyer import notification

from dotenv import load_dotenv
from telegram import Bot

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
# channel = "MeshTW"
channel = os.getenv("MQTT_CHANNEL")
# key = "1PG7OiApB1nwvP+rz05pAQ=="
# key = "isDhHrNpJPlGX3GBJBX6kjuK7KQNp4Z0M7OTDpnX5N4="
key = os.getenv("MQTT_MESH_KEY") #MeshTWtest

padded_key = key.ljust(len(key) + ((4 - (len(key) % 4)) % 4), '=')
replaced_key = padded_key.replace('-', '+').replace('_', '/')
key = replaced_key

broadcast_id = 4294967295

# Convert hex to int and remove '!'
node_number = int('abcd', 16)

async def send_telegram_message(bot, chat_id, text_payload):
    await bot.send_message(chat_id=chat_id, text=text_payload)

def process_message(mp, text_payload, is_encrypted, client_id):

    text = {
        "message": text_payload,
        "gateway": client_id,
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

def decode_encrypted(message_packet,client_id):
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

        # print('message_packet',message_packet)

        if message_packet.decoded.portnum == portnums_pb2.TEXT_MESSAGE_APP:
            text_payload = message_packet.decoded.payload.decode("utf-8")
            is_encrypted = True
            process_message(message_packet, text_payload, is_encrypted, client_id)
            # print(f"{text_payload}")
            return text_payload


        elif message_packet.decoded.portnum == portnums_pb2.NODEINFO_APP:
                info = mesh_pb2.User()
                info.ParseFromString(message_packet.decoded.payload)
                print(info)
                # notification.notify(
                # title = "Meshtastic",
                # message = f"{info}",
                # timeout = 10
                # )
        elif message_packet.decoded.portnum == portnums_pb2.POSITION_APP:
            pos = mesh_pb2.Position()
            pos.ParseFromString(message_packet.decoded.payload)
            print('pos',pos)

        elif message_packet.decoded.portnum == portnums_pb2.TELEMETRY_APP:
            env = telemetry_pb2.Telemetry()
            env.ParseFromString(message_packet.decoded.payload)
            print(env)

    except Exception as e:
        print(f"Decryption failed: {str(e)}")

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        print(f"Connected to {MQTT_BROKER} on topic {channel}")
    else:
        print(f"Failed to connect to MQTT broker with result code {str(rc)}")

def on_message(client, userdata, msg):
    # print("%-20s %d %s" % (msg.topic, msg.qos, msg.payload))
    service_envelope = mqtt_pb2.ServiceEnvelope()
    try:
        # print('msg',msg)
        service_envelope.ParseFromString(msg.payload)
        # print('service_envelope',service_envelope)
        message_packet = service_envelope.packet
        # print('message_packet',message_packet)
    except Exception as e:
        print(f"Error parsing message: {str(e)}")
        return

    # 獲取發出訊息的 client_id
    topic_parts = msg.topic.split('/')
    if len(topic_parts) >= 3:
        client_id = topic_parts[-1]
        print("Message sent by client_id:", client_id)
    else:
        print("Unable to determine client_id from topic:", msg.topic)

    if message_packet.HasField("encrypted") and not message_packet.HasField("decoded"):
        text_payload = decode_encrypted(message_packet,client_id)

        try:
            msg_with_clientid = client_id + ': ' + text_payload
            asyncio.get_event_loop().run_until_complete(send_telegram_message(bot, TELEGRAM_CHAT_ID, msg_with_clientid))
        except Exception as e:
            print(f"Error parsing message: {str(e)}")
            return

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