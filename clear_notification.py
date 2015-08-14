import paho.mqtt.client as mqtt
import logging
from threading import Thread
from time import sleep

_logger = logging.getLogger("sanji.remote.notification")


def clear_notification():

    topics = []
    client = mqtt.Client()

    def on_connect(client, userdata, rc):
        client.subscribe("/cgs/+/connection_status")

    def on_message(client, userdata, msg):
        if msg.payload == "":
            return

        _logger.debug("push topic: " + msg.topic + " " + str(msg.payload))
        topics.append(msg.topic)

    def clear_topics():
        sleep(2)
        for topic in topics:
            _logger.info("clear notification of " + topic)
            client.publish(topic, payload="", retain=True)
        sleep(1)
        client.disconnect()

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect("localhost", 1883, 60)

    thread = Thread(target=clear_topics)
    thread.start()

    client.loop_forever()
