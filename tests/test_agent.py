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
    from agent import restart_broker
    from agent import Index
except ImportError as e:
    raise e


class TestFunctionClass(unittest.TestCase):

    def test_generate_conf(self):
        """ should generate bridge config """
        output = "connection sanji-remote\naddress localhost\n" +\
                 "clientid test-id\ncleansession true\n" +\
                 "topic # in 2 / /test-id/\ntopic /+/controller out 2\n" +\
                 "topic /+/remote out 2\n"
        path = os.path.dirname(os.path.realpath(__file__))

        with open(path + "/../conf/bridge.conf.tmpl") as f:
            tmpl = f.read()
            m = mock_open()
            with patch("agent.open", m, create=True):
                mock = m()
                mock.read.return_value = tmpl
                generate_conf(
                    "test-id",
                    "localhost",
                    templ_file=path + "/../conf/bridge.conf.tmpl",
                    conf_file="/tmp/test-bridge.conf")

                self.assertEqual(m.mock_calls[1],
                                 call(path + "/../conf/bridge.conf.tmpl"))
                self.assertEqual(m.mock_calls[5],
                                 call("/tmp/test-bridge.conf", "w"))

            mock = m()
            mock.write.assert_called_once_with(output)

    def test_restart_broker_true(self):
        """ should restart broker via service """
        with patch("agent.sh.service"):
            self.assertTrue(restart_broker())

    def test_restart_broker_false(self):
        """ should restart broker via service with exception"""
        with patch("agent.sh.service") as service:
            service.side_effect = Exception("error")
            self.assertFalse(restart_broker())


class TestIndexClass(unittest.TestCase):

    @patch("agent.restart_broker")
    @patch("agent.generate_conf")
    def setUp(self, generate_conf, restart_broker):
        os.environ["REMOTE_IP"] = "192.168.1.254"
        self.index = Index(connection=Mockup())

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
            call('/%s/system/time' % self.index.__CLIENT_ID__,
                 topic='/%s/controller' % self.index.__SERVER_ID__,
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

        self.index.publish.get = MagicMock(return_value=resp_msg)
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
        self.index.publish.get = Mock(side_effect=TimeoutError())
        resp = Mock()
        self.index.remote(msg, resp, test=True)
        resp.assert_called_once_with(
            code=500, data={"message": "Remote requests timeout"})

if __name__ == "__main__":
    FORMAT = "%(asctime)s - %(levelname)s - %(lineno)s - %(message)s"
    logging.basicConfig(level=0, format=FORMAT)
    logger = logging.getLogger("Index")
    unittest.main()
