import numpy as np
import datetime as dt
import obspy as obs
from obspy.clients.fdsn import Client
import requests
import ipdb


def get_avail(network, station, location, channels, sampling_rate, dates):
    # stream = requests.get('https://service.iris.edu/fdsnws/availability/1/query?net=UW&sta=DOSE&loc=--&cha=BHZ&nodata=404&format=text', stream=True)
    avail_url = ("https://service.iris.edu/fdsnws/availability/1/query?"
             "net={network}&"
             "sta={station}&"
             "loc={location}&"
             "cha={channel}&"
             "start={starttime}&"
             "end={endtime}&"
             "nodata=404&format=text"
             )

    n_dates = len(dates)
    if not isinstance(channels, list):
        channels = [channels]
    n_channels = len(channels)
    avail = np.zeros((n_dates, n_channels), dtype=np.single)

    start_time = dates[0].strftime('%Y-%m-%dT00:00:00.000000Z')
    stop_time = dates[-1].strftime('%Y-%m-%dT00:00:00.000000Z')

    
    for c in range(n_channels):
        url = avail_url.format(network=network,
                               station=station,
                               location=location,
                               channel=channels[c],
                               starttime=start_time,
                               endtime=stop_time
                               )
        avail_stream = requests.get(url, stream=True)
        
        # UW DOSE -- BHZ M 40.0 2019-05-03T01:20:59.315000Z 2019-05-03T01:23:10.740000Z
        skip_line = True
        for line in avail_stream.iter_lines():
            if skip_line:
                skip_line = False
                continue

            split_line = line.decode('ascii').split()
            assert split_line[0] == network
            assert split_line[1] == station
            assert split_line[3] == channels[c]
            
            # who knows what happened, but not worth our time
            if float(split_line[5]) != sampling_rate:
                continue

            line_start = obs.UTCDateTime(split_line[6])
            line_stop = obs.UTCDateTime(split_line[7])

            line_time = line_start
            line_left = (line_stop - line_start) / 86400 # in days

            # if continuous time is less than 1 hour, skip it; it's not worth our time
            if line_left < 1 / 24:
                continue

            # check if start and stop time are on the same day
            if line_time.replace(hour=0, minute=0, second=0, microsecond=0) != line_stop.replace(hour=0, minute=0, second=0, microsecond=0):
                # first day until midnight
                next_day = (line_time + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

                day_idx = dates.index(line_time.replace(hour=0, minute=0, second=0, microsecond=0))
                avail[day_idx, c] += (next_day - line_time) / 86400

                # now deal with everything after the first day
                line_time = next_day
                line_left = (line_stop - line_time) / 86400

                # can simply add 1 to every day that is complete
                if line_left > 1:
                    day_idx = dates.index(line_time.replace(hour=0, minute=0, second=0, microsecond=0))
                    avail[day_idx:day_idx + int(line_left), c] += 1
                    
                    line_time = (line_time + dt.timedelta(days=int(line_left))).replace(hour=0, minute=0, second=0, microsecond=0)
                    line_left -= int(line_left)

            # last (partial) day of the line
            day_idx = dates.index(line_time.replace(hour=0, minute=0, second=0, microsecond=0))

            avail[day_idx, c] += (line_stop - line_time) / 86400.

    return avail

out_file = 'avail.txt'

networks = 'UW,PB,CC,CN,C8'
min_latitude = 46
max_latitude = 51
min_longitude = -129
max_longitude = -121.5
location = '*'
channels_search = 'BHN,BHE,BHZ,HHN,HHE,HHZ,EHN,EHE,EHZ'
sampling_rate = 40.
start_time = '2005-01-01T00:00:00'
stop_time = '2023-06-01T00:00:00'
start_before = '2010-01-01T00:00:00'
stop_after = '2020-01-01T00:00:00'
start_date = obs.UTCDateTime(start_time)
stop_date = obs.UTCDateTime(stop_time)
start_before_date = obs.UTCDateTime(start_before)
stop_after_date = obs.UTCDateTime(stop_after)

client = Client('IRIS')
inventory = client.get_stations(network=networks,
                                channel=channels_search,
                                minlatitude=min_latitude,
                                maxlatitude=max_latitude,
                                minlongitude=min_longitude,
                                maxlongitude=max_longitude,
                                starttime=start_date,
                                endtime=stop_date,
                                level='channel')

for network in inventory:
    for station in network:
        earliest_data = stop_date
        latest_data = start_date

        for channel in station:
            if channel.start_date < earliest_data:
                earliest_data = channel.start_date

            if channel.end_date is None:
                latest_data = None
            elif channel.end_date > latest_data:
                latest_data = channel.end_date

        if earliest_data > start_before_date:
            inventory = inventory.remove(station=station.code, keep_empty=False)

        if latest_data is not None and latest_data < stop_after_date:
            inventory = inventory.remove(station=station.code, keep_empty=False)

dates = []
date = start_date
while date <= stop_date:
    dates.append(date)
    date += dt.timedelta(days=1)

n_dates = len(dates)

with open(out_file, 'w+') as out:
    for network in inventory:
        for station in network:
            out.write('{}.{} | '.format(network.code, station.code))
            channel_ids = []
            for channel in station:
                channel_ids.append('{}:{:d}'.format(channel.code, int(channel.sample_rate)))

            channel_ids = set(channel_ids)

            timer = dt.datetime.now()
            for channel_id in channel_ids:
                channel = channel_id.split(':')[0]
                sampling_rate = float(channel_id.split(':')[1])
                avail = get_avail(network.code, station.code, '*', channel, sampling_rate, dates)

                out.write('{}={} '.format(channel_id, np.sum(avail)))
        
            out.write('\n')
            print('It took {:.2f}s for {}:{}.'.format((dt.datetime.now() - timer).total_seconds(), network.code, station.code))