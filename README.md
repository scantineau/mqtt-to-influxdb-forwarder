# IoT MQTT to InfluxDB forwarder #

This tool forwards IoT sensor data from a MQTT broker to an InfluxDB instance.

## Docker usage ##

    version: '3'
    services:
      mqtt2influxdb:
        image: scantineau/mqtt2influxdb:latest
        container_name: mqtt2influxdb
        environment:
          - TZ=Europe/Brussels
        volumes:
          - ./mqtt2influxdb/:/config/:ro
        restart: always
    
## Configuration ##

Configuration is yaml based and must be named config.yaml

Here is an example :

```
mqtt:
  host: yourMqttHost
  user: mqttUser
  password: mqttPassword
influx:
  host: yourInfluxdbHost
  user: influxdbUser
  password: influxdbPassword
  database: aDatabaseName
nodes:
  - name: weather
    regex: "(?P<node_name>token_pattern)/(?P<measurement_name>token_pattern)"
  - name: sensors
    regex: "(?P<node_name>token_pattern)/(?P<room>token_pattern)/(?P<measurement_name>token_pattern)/(token_pattern)"
verbose: true
```

Please notice that `token_pattern` is a shortcut to a fixed pattern : `(?:\w|-|\.)+`, but you can use your own. 

### Examples MQTT topic structure ###

A simple weather station with some sensors may publish its data like this:

    weather/uv: 0 (UV indev)
    weather/temp: 18.80 (°C)
    weather/pressure: 1010.77 (hPa)
    weather/bat: 4.55 (V)

Here, 'weather' is the node name and 'humidity', 'light' and 'temperature' are
measurement names. 0, 18.80, 1010.88 and 4.55 are measurement values. The units
are not transmitted, so any consumer of the data has to know how to interpret
the raw values.

Another group of sensors may publish its data like this:

    sensors/livingroom/temperature/state: 20.80 (°C)
    sensors/bedroom/temperature/state: 18.40 (°C)
    sensors/kitchen/temperature/state: 21.60 (°C)
    sensors/livingroom/humidity/state: 45.00 (%)
    sensors/bedroom/humidity/state: 55.00 (%)
    sensors/kitchen/humidity/state: 50.00 (%)
    sensors/livingroom/co/state: OK
    sensors/bedroom/co/state: OK
    sensors/kitchen/co/state: OK

Here, 'sensors' is the node name and 'temperature', 'humidity' and 'co' are
measurement names (see configuration section)

And finally 'livingroom', 'bedroom', 'kitchen' will be converted to tags. 

## Translation to InfluxDB data structure ##

The MQTT topic structure and measurement values are mapped as follows:

- the measurement name becomes the InfluxDB measurement name
- the measurement value is stored as a field named 'value'.
- all other regex group are stored as tags

Any measurements which look numeric will be converted to
a float.

### Example translation ###

The following log excerpt should make the translation clearer:

    DEBUG:forwarder.MQTTSource:Received MQTT message for topic weather/uv with payload 0
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {'value': 0.0}, 'tags': {'sensor_node': 'weather'}, 'measurement': 'uv'}
    DEBUG:forwarder.MQTTSource:Received MQTT message for topic weather/temp with payload 18.80
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {'value': 18.8}, 'tags': {'sensor_node': 'weather'}, 'measurement': 'temp'}
    DEBUG:forwarder.MQTTSource:Received MQTT message for topic weather/pressure with payload 1010.77
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {'value': 1010.77}, 'tags': {'sensor_node': 'weather'}, 'measurement': 'pressure'}
    DEBUG:forwarder.MQTTSource:Received MQTT message for topic weather/bat with payload 4.55
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {'value': 4.55}, 'tags': {'sensor_node': 'weather'}, 'measurement': 'bat'}
    DEBUG:forwarder.MQTTSource:Received MQTT message for topic sensors/kitchen/co/state with payload OK
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {'value': b'OK'}, 'tags': {'node_name': 'sensors', 'room': 'kitchen'}, 'measurement': 'co'}

## Complex measurements ##

If the MQTT message payload can be decoded into a JSON object, it is considered a
complex measurement: a single measurement consisting of several related data points.
The JSON object is interpreted as multiple InfluxDB field key-value pairs.
In this case, there is no automatic mapping of the measurement value to the field
named 'value'.

### Example translation ###

An example translation for a complex measurement:

    DEBUG:forwarder.MQTTSource:Received MQTT message for topic heaterroom/boiler-led with payload {"valid":true,"dark_duty_cycle":0,"color":"amber"}
    DEBUG:forwarder.InfluxStore:Writing InfluxDB point: {'fields': {u'color': u'amber', u'valid': 1.0, u'dark_duty_cycle': 0.0}, 'tags': {'sensor_node': 'heaterroom'}, 'measurement': 'boiler-led'}


### Example InfluxDB query ###

    select value from bat;
    select value from bat where sensor_node = 'weather' limit 10;
    select value from bat,uv,temp,pressure limit 20; 

The data stored in InfluxDB via this forwarder are easily visualized with [Grafana](http://grafana.org/)

## License ##

See the LICENSE file.

## Versioning ##

[Semantic Versioning](http://www.semver.org)
