#!/usr/bin/env python
# -*- coding: UTF-8 -*-

import os
import sh
import uuid
import logging

from string import Template
from sanji.core import Sanji
from sanji.core import Route
from sanji.session import TimeoutError
from sanji.connection.mqtt import Mqtt

logger = logging.getLogger()
prefixPath = os.path.dirname(os.path.realpath(__file__))


def generate_conf(data, templ_file, conf_file):
    """ Generate mosquitto conf from Template """
    logger.debug("load %s config template", (templ_file,))
    with open(templ_file) as f:
        template_str = f.read()
    tmpl = Template(template_str)

    logger.debug("write config file to %s" % conf_file)
    with open(conf_file, "w") as f:
        f.write(tmpl.substitute(data))


def generate_server_conf(
    port,
    templ_file="%s/conf/tls_psk_listener.conf.tmpl" % prefixPath,
    conf_file="/etc/mosquitto/conf.d/tls_psk_listener.conf"
):
    """ Generate mosquitto conf from Template """

    logger.debug("load tls_psk_listener config template")
    with open(templ_file) as f:
        template_str = f.read()
    tmpl = Template(template_str)

    logger.debug("write tls_psk_listener.conf to %s" % conf_file)
    with open(conf_file, "w") as f:
        f.write(tmpl.substitute({
            "port": port
        }))


def restart_broker():
    try:
        sh.service("mosquitto", "restart", _timeout=30)
        return True
    except Exception as e:
        logger.debug("restart error: %s" % e)
        try:
            sh.killall("mosquitto")
            sh.mosquitto("-c", "/etc/mosquitto/mosquitto.conf", _bg=True)
        except Exception, e:
            return False
        return True


class Index(Sanji):

    def init(self, *args, **kwargs):
        # Local Broker
        self.__LOCAL_HOST__ = os.getenv("LOCAL_HOST", "localhost")
        self.__LOCAL_PORT__ = os.getenv("LOCAL_PORT", 1883)
        self.__LOCAL_ID__ = os.getenv(
            "LOCAL_ID", 'LOCAL_ID-%s' % uuid.uuid4().hex)

        # Bridge to Remote Broker
        self.__REMOTE_HOST__ = os.getenv("REMOTE_HOST", None)
        self.__REMOTE_PORT__ = os.getenv("REMOTE_PORT", 1883)
        self.__REMOTE_ID__ = os.getenv("REMOTE_ID", None)
        self.__BG_ID__ = os.getenv("BG_ID", None)
        self.__BG_PSK__ = os.getenv("BG_PSK", None)

        # Setup for PSK encrypt port
        self.__ENCRYPT_PORT__ = os.getenv("ENCRYPT_PORT", None)
        self.__PSK_FILE__ = os.getenv(
            "PSK_FILE", "/etc/mosquitto/psk-list")
        self.__PSK_HINT__ = os.getenv("PSK_HINT", "hint")

        # Generate general config file
        generate_conf({
            "local_host": self.__LOCAL_HOST__,
            "local_port": self.__LOCAL_PORT__
        },
            "%s/conf/mosquitto.conf.tmpl" % prefixPath,
            "/etc/mosquitto/mosquitto.conf"
        )

        if self.__ENCRYPT_PORT__ is not None:
            generate_conf({
                "encrypt_port": self.__ENCRYPT_PORT__,
                "psk_file": self.__PSK_FILE__,
                "psk_hint": self.__PSK_HINT__
            },
                "%s/conf/tls_psk_listener.conf.tmpl" % prefixPath,
                "/etc/mosquitto/conf.d/tls_psk_listener.conf"
            )
            logger.debug("Enable encrypt port: %s with psk-file: %s" %
                         (self.__ENCRYPT_PORT__, self.__PSK_FILE__))

        if self.__REMOTE_ID__ is not None:
            # TODO: no provide BG_ID, BG_PSK
            generate_conf({
                "id": self.__LOCAL_ID__,
                "address": "%s:%s" % (self.__REMOTE_HOST__,
                                      self.__REMOTE_PORT__),
                "bridge_identity": self.__BG_ID__,
                "bridge_psk": self.__BG_PSK__
            },
                "%s/conf/bridge.conf.tmpl" % prefixPath,
                "/etc/mosquitto/conf.d/sanji.conf"
            )
            logger.debug("Enable bridge mode connect to: %s:%s" %
                         (self.__REMOTE_HOST__, self.__REMOTE_PORT__))
            restart_broker()

    def run(self):
        if self.__REMOTE_ID__ is None:
            self._conn.set_tunnel(
                'remote_agent', "/%s/remote" % self.__LOCAL_ID__)
            self._conn.set_tunnel(
                'remote_controller', "/%s/controller" % self.__LOCAL_ID__)
        self._conn.set_tunnel('remote', "/remote")

    @Route(resource="/.*")
    def event_proxy(self, message):
        """ View callback (self, message) """
        if "/remote" in message.resource:  # don't proxy self's req's response
            return

        if self.__REMOTE_ID__ is None:
            # convert remote event to local
            if message.resource[:4] == "/cg-":
                getattr(self.publish.event, message.method)(
                    message.resource,
                    data=getattr(message, 'data', None))
                return

        # send to remote broker
        getattr(self.publish.event, message.method)(
            "/%s%s" % (self.__LOCAL_ID__, message.resource),
            topic="/%s/controller" % self.__REMOTE_ID__,
            data=getattr(message, 'data', None))

    @Route(resource="/remote/:to_id")
    def remote(self, message, response):
        """ model callback (self, message, responsse) """
        try:
            result = getattr(self.publish.direct, message.data["method"])(
                message.data["resource"],
                topic="/%s/controller" % message.param["to_id"],
                tunnel="/%s/remote" % self.__LOCAL_ID__,
                data=message.data["data"])
            return response(code=result.code, data=result.to_dict())
        except TimeoutError:
            return response(
                code=500, data={"message": "Remote requests timeout"})


if __name__ == "__main__":
    # disabling sh logger
    sh_logger = logging.getLogger("sh")
    sh_logger.propagate = False
    sh_logger.addHandler(logging.NullHandler())
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger("Remote")
    index = Index(connection=Mqtt())
    index.start()
