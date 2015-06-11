#!/usr/bin/env python
# -*- coding: UTF-8 -*-


import os
import sys
import logging

from mock import MagicMock
from mock import Mock
from mock import patch
from mock import call
from mock import mock_open
from sanji.connection.mockup import Mockup
from sanji.message import Message
from sanji.session import TimeoutError

if sys.version_info >= (2, 7):
    import unittest
else:
    import unittest2 as unittest

try:
    sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../")
    from agent import generate_conf
    from agent import Index
except ImportError as e:
    raise e


class TestFunctionClass(unittest.TestCase):

    def test_generate_encrypt_conf(self):
        """ should generate encrypt config """
        output = "bind_address 0.0.0.0\n" +\
                 "port 8883\n" +\
                 "persistence false\n" +\
                 "psk_file /etc/mosquitto/psk-list\n" +\
                 "psk_hint hint\n\n" +\
                 "connection sanji-internel\n" +\
                 "address localhost:1883\n" +\
                 "clientid server-internel\n" +\
                 "cleansession true\n" +\
                 "topic # both 2\n"

        path = os.path.dirname(os.path.realpath(__file__))
        with open(path + "/../conf/external_listener.conf.tmpl") as f:
            tmpl = f.read()
            m = mock_open()
            with patch("agent.open", m, create=True):
                mock = m()
                mock.read.return_value = tmpl
                generate_conf({
                    "id": "server",
                    "external_port": 8883,
                    "external_host": "0.0.0.0",
                    "psk_secret": "psk_file /etc/mosquitto/psk-list\n" +
                                  "psk_hint hint"
                },
                    path + "/../conf/external_listener.conf.tmpl",
                    "/tmp/external_listener.conf"
                )

                self.assertEqual(
                    m.mock_calls[1],
                    call(path + "/../conf/external_listener.conf.tmpl"))
                self.assertEqual(
                    m.mock_calls[5],
                    call("/tmp/external_listener.conf", "w"))

            mock = m()
            mock.write.assert_called_once_with(output)

    def test_generate_general_conf(self):
        """ should generate mosquitto config """
        output = "bind_address localhost\n" +\
                 "port 1883\npid_file /var/run/mosquitto.pid\n" +\
                 "persistence false\n" +\
                 "log_dest file /var/log/mosquitto/mosquitto.log\n" +\
                 "include_dir /etc/mosquitto/conf.d\n"

        path = os.path.dirname(os.path.realpath(__file__))
        with open(path + "/../conf/mosquitto.conf.tmpl") as f:
            tmpl = f.read()
            m = mock_open()
            with patch("agent.open", m, create=True):
                mock = m()
                mock.read.return_value = tmpl
                generate_conf({
                    "local_host": "localhost",
                    "local_port": 1883
                },
                    path + "/../conf/mosquitto.conf.tmpl",
                    "/tmp/mosquitto.conf"
                )

                self.assertEqual(
                    m.mock_calls[1],
                    call(path + "/../conf/mosquitto.conf.tmpl"))
                self.assertEqual(
                    m.mock_calls[5],
                    call("/tmp/mosquitto.conf", "w"))

            mock = m()
            mock.write.assert_called_once_with(output)


class TestIndexClass(unittest.TestCase):

    @patch("agent.restart_broker")
    @patch("agent.generate_conf")
    @patch("agent.sh")
    def setUp(self, sh, generate_conf, restart_broker):
        os.environ["REMOTE_HOST"] = "192.168.1.254"
        self.index = Index(connection=Mockup())
        self.index.__REMOTE_ID__ = "This-is-__REMOTE_ID__"

    def tearDown(self):
        self.index.stop()
        self.index = None

    def test_event_proxy(self):
        """ should proxy all views to remote except: /remote """
        msg = Message({
            "resource": "/system/time",
            "method": "get"
        })
        self.index.publish.event.get = MagicMock()
        self.index.event_proxy(msg, test=True)
        self.assertEqual(
            self.index.publish.event.get.mock_calls[0],
            call('/%s/system/time' % self.index.__LOCAL_ID__,
                 topic='/%s/controller' % self.index.__REMOTE_ID__,
                 data=None))

    def test_remote(self):
        """ should send a remote request to /remote/:to_id """
        msg = Message({
            "id": 334567,
            "resource": "/remote/cg-11-22-33",
            "method": "post",
            "param": {
                "to_id": "cg-11-22-33"
            },
            "data": {
                "method": "get",
                "resource": "/system/time",
                "data": {}
            }
        }, generate_id=False)

        resp_msg = Message({
            "id": 12345,
            "code": 200,
            "resource": "/system/time",
            "method": "get",
            "data": {}
        }, generate_id=False)

        self.index.publish.direct.get = MagicMock(return_value=resp_msg)
        resp = Mock()
        self.index.remote(msg, resp, test=True)
        resp.assert_called_once_with(code=200, data=resp_msg.to_dict())

    def test_remote_with_error(self):
        """ should send a remote request to /remote/:to_id with Exception"""
        msg = Message({
            "id": 334567,
            "resource": "/remote/cg-11-22-33",
            "method": "post",
            "param": {
                "to_id": "cg-11-22-33"
            },
            "data": {
                "method": "get",
                "resource": "/system/time",
                "data": {}
            }
        }, generate_id=False)
        self.index.publish.direct.get = Mock(side_effect=TimeoutError())
        resp = Mock()
        self.index.remote(msg, resp, test=True)
        resp.assert_called_once_with(
            code=500, data={"message": "Remote requests timeout"})

if __name__ == "__main__":
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=20, format=FORMAT)
    logger = logging.getLogger("Index")
    unittest.main()
