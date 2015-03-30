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


def generate_conf(
    id,
    address,
    templ_file="%s/conf/bridge.conf.tmpl" % prefixPath,
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
        self.__REMOTE_IP__ = os.getenv("REMOTE_IP", None)
        self.__REMOTE_PORT__ = os.getenv("REMOTE_PORT", 1883)
        self.__REMOTE_ID__ = os.getenv("REMOTE_ID", None)
        self.__LOCAL_ID__ = os.getenv(
            "LOCAL_ID", 'LOCAL_ID-%s' % uuid.uuid4().hex)

        if self.__REMOTE_ID__ is not None:
            logger.debug("Running in client mode")
            generate_conf(
                self.__LOCAL_ID__, "%s %s" % (self.__REMOTE_IP__,
                                              self.__REMOTE_PORT__))
            restart_broker()
        else:
            logger.debug("Running in server mode")

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


if __name__ == "__main__":
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger("Remote")
    index = Index(connection=Mqtt())
    index.start()
