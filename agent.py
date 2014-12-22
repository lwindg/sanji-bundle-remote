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


def generate_conf(
    id,
    address,
    templ_file="./conf/bridge.conf.tmpl",
    conf_file="/etc/mosquitto/conf.d/sanji.conf"
):
    """ Generate mosquitto conf from Template """

    logger.debug("load bridge config template")
    with open(templ_file) as f:
        template_str = f.read()
    tmpl = Template(template_str)

    logger.debug("write bridge.conf to %s" % conf_file)
    with open(conf_file, "w") as f:
        f.write(tmpl.substitute({
            "address": address,
            "id": id
        }))


def restart_broker():
    try:
        sh.service("mosquitto", "restart", _timeout=30)
        return True
    except Exception as e:
        logger.debug("restart error: %s" % e)
        return False


class Index(Sanji):

    def init(self, *args, **kwargs):
        self.__CLIENT_ID__ = os.getenv("CG_ID", 'cg-id-%s' % uuid.uuid4().hex)
        self.__SERVER_ID__ = os.getenv("CS_ID", 'cs-id-%s' % uuid.uuid4().hex)
        self.__REMOTE_IP__ = os.getenv("REMOTE_IP", None)
        self.__REMOTE_PORT__ = os.getenv("REMOTE_PORT", 1883)

        print os.getenv("REMOTE_IP", None)

        if self.__REMOTE_IP__ is None:
            raise ValueError("ENV: REMOTE_IP is not set")

        generate_conf(
            self.__CLIENT_ID__, "%s %s" % (self.__REMOTE_IP__,
                                           self.__REMOTE_PORT__))
        restart_broker()

    def run(self):
        self._conn.set_tunnel('remote', "/remote")

    @Route(resource="/.*")
    def event_proxy(self, message):
        """ View callback (self, message) """
        if "/remote" in message.resource:  # don't proxy self's req's response
            return

        # send to remote broker
        getattr(self.publish.event, message.method)(
            "/%s%s" % (self.__CLIENT_ID__, message.resource),
            topic="/%s/controller" % self.__SERVER_ID__,
            data=getattr(message, 'data', None))

    @Route(resource="/remote/:to_id")
    def remote(self, message, response):
        """ model callback (self, message, responsse) """
        try:
            result = getattr(self.publish, message.data["method"])(
                message.resource,
                topic="/%s/remote" % message.param["to_id"],
                data=message.data["data"])
            return response(code=result.code, data=result.to_dict())
        except TimeoutError:
            return response(
                code=500, data={"message": "Remote requests timeout"})


if __name__ == "__main__":
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger("Remote")
    index = Index(connection=Mqtt())
    index.start()
