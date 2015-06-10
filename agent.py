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

from voluptuous import Schema
from voluptuous import REMOVE_EXTRA
from voluptuous import Range
from voluptuous import All

_logger = logging.getLogger("sanji.remote")
prefixPath = os.path.dirname(os.path.realpath(__file__))


def generate_conf(data, templ_file, conf_file):
    """ Generate mosquitto conf from Template """
    _logger.debug("load %s config template", (templ_file,))
    with open(templ_file) as f:
        template_str = f.read()
    tmpl = Template(template_str)

    _logger.debug("write config file to %s" % conf_file)
    with open(conf_file, "w") as f:
        f.write(tmpl.substitute(data))


def generate_server_conf(
    port,
    templ_file="%s/conf/external_listener.conf.tmpl" % prefixPath,
    conf_file="/etc/mosquitto/conf.d/external_listener.conf"
):
    """ Generate mosquitto conf from Template """

    _logger.debug("load external_listener config template")
    with open(templ_file) as f:
        template_str = f.read()
    tmpl = Template(template_str)

    _logger.debug("write external_listener.conf to %s" % conf_file)
    with open(conf_file, "w") as f:
        f.write(tmpl.substitute({
            "port": port
        }))


def stop_broker(process=None):
    if process:
        _logger.debug("Killing previous broker via process")
        process.kill()
        return

    try:
        pid = sh.awk(
            sh.grep(sh.ps("ax"), "sanji-bridge"), "{print $1}").split()
        sh.kill(" ".join(pid))
        _logger.debug("Killing previous broker via pid")
    except:
        pass


def start_broker():
    ret = sh.mosquitto(
        "-c", "/etc/mosquitto/sanji-bridge.conf", _bg=True)
    _logger.debug("Bridge broker started.")

    return ret.process


def restart_broker(process=None):
    try:
        stop_broker(process)
        return start_broker()
    except Exception as e:
        _logger.debug("Restart error: %s" % str(e), exc_info=True)
        return None


class Index(Sanji):

    SCHEMA = Schema({
        "enable": All(int, Range(min=0, max=1))
    }, extra=REMOVE_EXTRA)

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

        # Setup for EXTERNAL Port and Host
        self.__EXTERNAL_PORT__ = os.getenv("EXTERNAL_PORT", None)
        self.__EXTERNAL_HOST__ = os.getenv("EXTERNAL_HOST", None)
        self.__TLS_ENABLED__ = os.getenv("TLS_ENABLED", False)
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

        if self.__EXTERNAL_PORT__ is not None \
                and self.__EXTERNAL_HOST__ is not None:
            psk_secret = ""
            if self.__TLS_ENABLED__ == "true":
                psk_secret = ("psk_file %s\npsk_hint %s" %
                              (self.__PSK_FILE__, self.__PSK_HINT__))
                _logger.debug("Enable PSK Secret with psk-file: %s" %
                              self.__PSK_FILE__)
            generate_conf({
                "external_port": self.__EXTERNAL_PORT__,
                "external_host": self.__EXTERNAL_HOST__,
                "psk_secret": psk_secret
            },
                "%s/conf/external_listener.conf.tmpl" % prefixPath,
                "/etc/mosquitto/conf.d/external_listener.conf"
            )
            _logger.debug("Enable external port: %s with psk-file: %s" %
                          (self.__EXTERNAL_PORT__, self.__PSK_FILE__))
        else:
            try:
                os.remove("/etc/mosquitto/conf.d/external_listener.conf")
                _logger.debug("Remove old encrypt port config.")
            except:
                pass

        sh.service("mosquitto", "restart")

        if self.__REMOTE_ID__ is not None:
            bridge_secret = ""
            if self.__BG_ID__ is not None and self.__BG_PSK__ is not None:
                bridge_secret = ("bridge_identity %s\nbridge_psk %s" %
                                 (self.__BG_ID__, self.__BG_PSK__,))

            generate_conf({
                "id": self.__LOCAL_ID__,
                "address": "%s:%s" % (self.__REMOTE_HOST__,
                                      self.__REMOTE_PORT__),
                "bridge_secret": bridge_secret
            },
                "%s/conf/bridge.conf.tmpl" % prefixPath,
                "/etc/mosquitto/sanji-bridge.conf"
            )
            _logger.debug("Enable bridge mode connect to: %s:%s" %
                          (self.__REMOTE_HOST__, self.__REMOTE_PORT__))
            self.bridge_process = restart_broker(None)

    def run(self):
        if self.__REMOTE_ID__ is None:
            self._conn.set_tunnel(
                'remote_server', "/%s/remote" % self.__LOCAL_ID__)
        self._conn.set_tunnel('remote', "/remote")

    @Route(resource="/.*")
    def event_proxy(self, message):
        """ View callback (self, message) """
        if self.__REMOTE_ID__ is None:
            return
        if "/remote" in message.resource:  # don't proxy self's req's response
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

    @Route(methods="put", resource="/system/remote", schema=SCHEMA)
    def restart_bridge(self, message, response):
        """ Restart remote broker """
        if self.__REMOTE_ID__ is None:
            return response(
                code=400, data={"message": "REMOTE_ID is not enabled."})

        if message.data["enable"] == 0:
            stop_broker(self.bridge_process)
            return response()

        self.bridge_process = restart_broker(self.bridge_process)
        if self.bridge_process is None:
            return response(
                code=500, data={"message": "Restart remote broker failed."})
        return response()

if __name__ == "__main__":
    # disabling sh _logger
    sh__logger = logging.getLogger("sh")
    sh__logger.propagate = False
    sh__logger.addHandler(logging.NullHandler())
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    _logger = logging.getLogger("Remote")
    index = Index(connection=Mqtt())
    index.start()
