#!/usr/bin/env python
# -*- coding: utf-8 -*-

# forwarder.py - forwards IoT sensor data from MQTT to InfluxDB
#
# Copyright (C) 2020 Sébastien CANTINEAU <sebastien.cantineau@gmail.com>
# Based on Michael Haas <haas@computerlinguist.org> project
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA

import json
import logging
import paho.mqtt.client as mqtt
import re
import requests.exceptions
import sys
import yaml
from influxdb import InfluxDBClient

cache = {}


class MessageStore(object):

    def store_msg(self, tags, measurement_name, value):
        raise NotImplementedError()


class InfluxStore(MessageStore):
    logger = logging.getLogger("forwarder.InfluxStore")

    def __init__(self, host, port, username, password, database):
        self.influx_client = InfluxDBClient(
            host=host, port=port, username=username, password=password, database=database)
        self.influx_client.create_database(database)

    def store_msg(self, tags, measurement_name, data):
        if not isinstance(data, dict):
            raise ValueError('data must be given as dict!')
        influx_msg = {
            'measurement': measurement_name,
            'tags': tags,
            'fields': data
        }
        self.logger.debug("Writing InfluxDB point: %s", influx_msg)
        try:
            self.influx_client.write_points([influx_msg])
        except requests.exceptions.ConnectionError as e:
            self.logger.exception(e)


class MessageSource(object):

    def register_store(self, store):
        if not hasattr(self, '_stores'):
            self._stores = []
        self._stores.append(store)

    @property
    def stores(self):
        # return copy
        return list(self._stores)


def build_dict(seq, key):
    return dict((d[key], dict(d, index=index)) for (index, d) in enumerate(seq))


def without_keys(d, keys):
    return {k: v for k, v in d.items() if k not in keys}


class MQTTSource(MessageSource):
    logger = logging.getLogger("forwarder.MQTTSource")

    def __init__(self, host, port, user, password, nodes, stringify_values_for_measurements):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.nodes = nodes
        self.stringify = stringify_values_for_measurements
        self.node_by_name = build_dict(nodes, key="name")
        self._setup_handlers()

    def _setup_handlers(self):
        self.client = mqtt.Client()
        if self.user is not None and self.password is not None:
            self.client.username_pw_set(self.user, self.password)

        def on_connect(client, userdata, flags, rc):
            self.logger.info("Connected with result code  %s", rc)
            # subscribe to /node_name/wildcard
            for node in self.nodes:
                topic = "{node_name}/#".format(node_name=node['name'])
                self.logger.info(
                    "Subscribing to topic %s for node_name %s", topic, node['name'])
                client.subscribe(topic)

        def on_message(client, userdata, msg):
            self.logger.debug(
                "Received MQTT message for topic %s with payload %s", msg.topic, msg.payload)
            token_pattern = '(?:\w|-|\.)+'

            regex = re.compile('(?P<node_name>' + token_pattern + ')/?')
            match = regex.match(msg.topic)
            if match is None:
                self.logger.warn(
                    "Could not extract node name from topic %s", msg.topic)
                return

            node_name = match.group('node_name')
            node = self.node_by_name.get(node_name, None)

            if node is None:
                self.logger.warn(
                    "Extract node_name %s from topic, but requested to receive messages for nodes %s", node_name,
                    self.nodes)
                return

            regex = re.compile(node['regex'].replace('token_pattern', token_pattern))
            match = regex.match(msg.topic)
            if match is None:
                self.logger.warn(
                    "Could not extract measurement name from topic %s", msg.topic)
                return

            measurement_name = match.group('measurement_name')

            value = msg.payload

            is_value_json_dict = False
            try:
                stored_message = json.loads(value)
                is_value_json_dict = isinstance(stored_message, dict)
            except ValueError:
                pass

            if is_value_json_dict:
                for key in stored_message.keys():
                    try:
                        stored_message[key] = float(stored_message[key])
                    except ValueError:
                        pass
            else:
                # if message is not a JSON DICT, only then check if we should stringify the value
                self.logger.debug(self.stringify)
                if measurement_name in self.stringify:
                    value = str(value)
                else:
                    try:
                        value = float(value)
                    except ValueError:
                        pass
                self.logger.debug(value)
                stored_message = {'value': value}

            global cache
            self.logger.debug("measurement_name : %s | data : %s", measurement_name, value)
            self.logger.debug("cache : %s", cache)
            if measurement_name in cache and cache[measurement_name] == value:
                self.logger.info("value did not changed for : %s, skipping", measurement_name)
            else:
                cache[measurement_name] = value


            self.logger.debug("Going to store")
            for store in self.stores:
                store.store_msg(without_keys(match.groupdict(), 'measurement_name'), measurement_name, stored_message)

        self.client.on_connect = on_connect
        self.client.on_message = on_message

    def start(self):
        self.client.connect(self.host, self.port)
        # Blocking call that processes network traffic, dispatches callbacks and
        # handles reconnecting.
        # Other loop*() functions are available that give a threaded interface and a
        # manual interface.
        self.client.loop_forever()


def main():
    logger = logging.getLogger("forwarder.main")
    config = None
    with open("/config/config.yaml", 'r') as stream:
        try:
            config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

    if config.get('verbose', False):
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    else:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    logger.debug("Begin of forwarder")

    store = InfluxStore(host=config['influx']['host'],
                        port=config['influx'].get('port', 8086),
                        username=config['influx']['user'],
                        password=config['influx']['password'],
                        database=config['influx']['database'])
    source = MQTTSource(host=config['mqtt']['host'],
                        port=config['mqtt'].get('port', 1883),
                        user=config['mqtt']['user'],
                        password=config['mqtt']['password'],
                        nodes=config['nodes'],
                        stringify_values_for_measurements=config.get('stringify_values_for_measurements', []))
    source.register_store(store)
    source.start()


if __name__ == '__main__':
    main()
