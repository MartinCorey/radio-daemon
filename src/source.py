import random
import time
import xmljson
import json
import threading
import xml.etree.ElementTree as ET
import datetime
import time
import os
import shutil
import subprocess
import signal
from pathlib import Path
from typing import List

import mutagen
import imghdr
import sys
from random import shuffle

import logging

DAEMON_DIR = "/home/elaine/app/source_daemon"


logging.basicConfig(level=logging.DEBUG, filename=f"{DAEMON_DIR}/log/app.log")


def to_pcm(file_path):
    # hardcoded: sample rate 44100, channels 2. IceS expects these two values (specified in ices.xml)
    cmd = ["ffmpeg", "-i", file_path, "-ar", "44100", "-ac", "2", "-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-"]

    ffmpeg_process = subprocess.run(cmd, capture_output=True)

    return ffmpeg_process.stdout


def update_metadata_file(track_metadata, ices_process, channel_index):
    track_metadata['starttime'] = time.time()
    #print(track_metadata)
    # add accessed metadata, sensitive to when this file is written!
    track_metadata['accessed'] = str(datetime.datetime.now(datetime.timezone.utc))

    with open(f"/tmp/metadata_{channel_index}.txt", 'w') as f:
        f.write("\n".join([f"{key}={track_metadata[key]}" for key in track_metadata]))

    # send signal to ices process that metadata.txt updated
    ices_process.send_signal(signal.SIGUSR1)


def update_image_files(dir, album_metadata, channel_index):
    image_file = album_metadata['image']
    segment_image_file = album_metadata['segment_cover']
    block_image_file = album_metadata['block_cover']
    shutil.copy(f"{dir}/{image_file}", f"/tmp/current_album_{channel_index}")
    shutil.copy(block_image_file, f"/tmp/current_block_{channel_index}")
    shutil.copy(segment_image_file, f"/tmp/current_segment_{channel_index}")


def get_file_metadata(file_path):
    f = mutagen.File(file_path)
    if f is None:  # if not audio/failed
        return None
    d = dict(f.tags)

    logging.debug(str(d))
    tags = {k: d[k][0] for k in d if isinstance(d[k], list)}  # make it not return a (key, singleton list) pair?
    length = f.info.length

    # add filename to tags:
    try:
        filename = file_path.split('/')[-1]
        tags['filename'] = filename
        artistAlbum = file_path.split('/')[-2]
        numberName = os.path.splitext(filename)[0]

        tags['artist'] = artistAlbum.split(" - ")[0]
        tags['album'] = artistAlbum.split(" - ")[1]
        tags['number'] = numberName.split(" - ")[0]
        tags['title'] = numberName.split(" - ")[1]
    except:
        pass
    return (tags, length)


def create_track_metadata(file_metadata, album_metadata, block):
    tags, length = file_metadata

    track_metadata = dict(album_metadata)  # copy
    for key in tags:
        if not key in track_metadata:
            track_metadata[key] = tags[key]

    track_metadata['length'] = str(length)
    track_metadata['genre'] = block.desc  # can be changed to general album metadata later
    return track_metadata


class Block:
    def __init__(self, start, end, desc, name, image_path):
        self.start = start
        self.end = end
        self.desc = desc
        self.name = name
        self.image_path = image_path
        self.segments = []

    def add_segment(self, segment):
        self.segments.append(segment)

    def shuffle_segments(self):
        shuffle(self.segments)


class Segment:
    def __init__(self, name, image_path):
        self.name = name
        self.image_path = image_path
        self.albums = []

    # automatically detects and stores the absolute path, image, and track list
    def add_album(self, dir, album_metadata, block):
        # for counting album duration
        # album_length = 0

        # get all tracks (sorted by filename!)
        track_filenames = sorted(os.listdir(dir))

        tracks = []
        for fn in track_filenames:
            file_path = f"{dir}/{fn}"

            # get file metadata
            file_metadata = get_file_metadata(file_path)
            if file_metadata is None:  # if not audio/failed, skip
                continue

            tags, length = file_metadata

            # update album length
            # album_length += length

            # create track metadata
            track_metadata = create_track_metadata(file_metadata, album_metadata, block)

            tracks.append((file_path, track_metadata))

        # auto find image file
        image_file = None
        file_type = None
        for file in os.listdir(dir):
            file_type = imghdr.what(f"{dir}/{file}")
            if file_type:
                image_file = file
                break

        # set image album metadata
        album_metadata['image'] = image_file
        album_metadata['block_name'] = block.name
        album_metadata['block_cover'] = block.image_path
        album_metadata['segment_name'] = self.name
        album_metadata['segment_cover'] = self.image_path

        self.albums.append((dir, tracks, album_metadata))


# brittle, but it works...
def parse_blocks(USER_CONFIG_PATH: str):
    blocks = []

    # read config
    tree = ET.parse(USER_CONFIG_PATH)
    root = tree.getroot()
    # parse blocks
    try:
        for block in root.findall('block'):
            start = datetime.time.fromisoformat(block.find('time').find('start').text)
            end = datetime.time.fromisoformat(block.find('time').find('end').text)
            desc = block.find('desc').text.strip()
            name = block.find('name').text.strip()
            block_cover = block.find('image').text.strip()
            b = Block(start, end, desc, name, block_cover)
            for segment in block.findall('segment'):
                seg_name = segment.find('name').text.strip()
                seg_img = segment.find('image').text.strip()
                s = Segment(seg_name, seg_img)

                # parse path to find album dirs
                albums_path = os.path.expanduser(segment.find('files').text.strip())

                # parse blacklisted album dirs
                blacklisted = {e.text.strip() for e in segment.find('blacklist').findall('album')}

                # add albums to slot in randomized order
                album_directories = os.listdir(albums_path)
                shuffle(album_directories)

                for album_dir in album_directories:
                    if album_dir not in blacklisted:
                        path = f"{albums_path}/{album_dir}"
                        # metadata_elements = [album.find(t) for t in ['title', 'artist', 'year']]
                        # metadata = {e.tag : e.text.strip() for e in metadata_elements if not (e is None)}
                        s.add_album(path, {}, b)

                b.add_segment(s)
            b.shuffle_segments()
            blocks.append(b)
    except:
        logging.exception("Config parse error:")
        logging.debug("Closing...")
        sys.exit(-1)

    for b in blocks:
        for s in b.segments:
            for dir, tracks, album_metadata in s.albums:
                logging.debug(f"parsed album: {dir.split('/')[-1]}")

    # sort wrt start time (valid asumming slots don't overlap!)
    # would be useful to add a check for this!
    blocks.sort(key=lambda b: b.start)

    return blocks


def get_remaining_seconds(block):
    current = datetime.datetime.now()
    end_delta = datetime.timedelta(hours=block.end.hour, minutes=block.end.minute)
    current_delta = datetime.timedelta(hours=current.hour, minutes=current.minute)

    return (end_delta.total_seconds() - current_delta.total_seconds()) % 86400  # seconds in 24 hours!


def get_seconds_to_start(current_date, slot):
    start_delta = datetime.timedelta(hours=slot.start.hour, minutes=slot.start.minute)
    current_delta = datetime.timedelta(hours=current_date.hour, minutes=current_date.minute)

    return (start_delta.total_seconds() - current_delta.total_seconds()) % 86400  # seconds in 24 hours!


# assumes slots are ordered in time
def find_current_block(blocks, offset):
    current_date = datetime.datetime.now()

    nearest_seconds_to_start = 86400
    nearest_index = -1
    for i in range(len(blocks)):
        seconds_to_start = get_seconds_to_start(current_date, blocks[i])
        if seconds_to_start <= nearest_seconds_to_start:
            nearest_seconds_to_start = seconds_to_start
            nearest_index = i

    if offset:
        return blocks[(nearest_index + 1) % len(blocks)]

    return blocks[nearest_index]


def has_day_passed(album_play_date):
    return (datetime.datetime.now() - album_play_date).total_seconds() >= 86400


def close_program(sub):
    sub.stdin.close()
    sub.wait()
    logging.debug(f"\nIceS closed with exit code: {sub.poll()}")
    sys.exit(0)

def radio(USER_CONFIG_PATH: str, ices_process, channel_index: int):
    blocks = parse_blocks(USER_CONFIG_PATH=USER_CONFIG_PATH)
    last_edited = os.path.getmtime(USER_CONFIG_PATH)

    # key=path, value=date_played
    # check if not here OR 24 hours have passed before playing
    # use bool flag to indicate if a slot got to play any albums
    # if not, sleep, wait for config changes lol
    ALBUM_BLACKLIST = dict()



    try:
        offset = False
        while True:
            restart = False  # flag initialize

            logging.debug("Finding time slot...")
            # find currently applicable slot
            block = find_current_block(blocks, offset)
            offset = False

            if not (block is None):
                logging.debug("Block found!")
                logging.debug(f"start: {block.start}")
                logging.debug(f"end: {block.end}")

                some_album_played = False
                # get slot albums
                albums = []
                for segment in block.segments:
                    for album in segment.albums:
                        albums.append(album)
                for dir, tracks, album_metadata in albums:
                    if restart:
                        break

                    # check if album is blacklisted:
                    if (not dir in ALBUM_BLACKLIST) or has_day_passed(ALBUM_BLACKLIST[dir]):
                        # update blacklist last_played
                        ALBUM_BLACKLIST[dir] = datetime.datetime.now()
                    else:
                        continue  # skip this album

                    remaining_seconds = get_remaining_seconds(block)
                    logging.debug(f"remaining seconds: {remaining_seconds}")
                    if remaining_seconds <= 900:
                        logging.debug("Ending time slot early...")
                        offset = True
                        break

                    # album playback successful
                    some_album_played = True

                    logging.debug("Accessing album at directory " + dir)
                    # update current image (find using imgdhr)
                    update_image_files(dir, album_metadata, channel_index)

                    # loop through tracks (cache album length?)
                    album_length = 0
                    for file_path, track_metadata in tracks:
                        length = float(track_metadata['length'])
                        album_length += length

                        # update metadata.txt
                        update_metadata_file(track_metadata, ices_process, channel_index=channel_index)
                        logging.debug("Metadata.txt updated!")

                        # decode file into raw pcm (ffmpeg run)
                        logging.debug(f"Converting file {track_metadata['filename']} to pcm:")
                        pcm = to_pcm(file_path)

                        # pipe pcm to ices (terminate after 5 minutes if applicable):
                        logging.debug("Writing pcm to IceS process stdin:")
                        ices_process.stdin.write(pcm)
                        ices_process.stdin.flush()

                        # check if config was edited
                        recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
                        if last_edited != recent_last_edited:
                            logging.debug("Config edited, updating slots and restarting...")
                            last_edited = recent_last_edited
                            blocks = parse_blocks(USER_CONFIG_PATH=USER_CONFIG_PATH)

                            # look for new slot
                            restart = True
                            offset = False
                            break

                    # Time slot finished

                    # check if album runtime has surpassed alloted slot time
                    if album_length >= remaining_seconds:
                        logging.debug("Album surpassed slot length. Seeking new slot...")
                        offset = False
                        break

                    # looping...

                # end of block!
                if not some_album_played:
                    logging.debug(
                        "No album played. Check that sufficient albums have been supplied. Sleeping for 5 minutes...")
                    time.sleep(300)

                    # check if config was edited
                    recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
                    if last_edited != recent_last_edited:
                        logging.debug("Config edited, updating slots and restarting...")
                        last_edited = recent_last_edited
                        blocks = parse_blocks(USER_CONFIG_PATH=USER_CONFIG_PATH)

            else:
                # sleep for an amount of time, play an intermission, etc... then try again
                logging.debug("No slot available. Check that slots are specified. Sleeping for 5 minutes...")
                time.sleep(300)

                # check if config was edited
                recent_last_edited = os.path.getmtime(USER_CONFIG_PATH)
                if last_edited != recent_last_edited:
                    logging.debug("Config edited, updating slots and restarting...")
                    last_edited = recent_last_edited
                    blocks = parse_blocks(USER_CONFIG_PATH=USER_CONFIG_PATH)

    except KeyboardInterrupt:
        logging.debug("Keyboard interrupt.")

    except:
        logging.exception("Unexpected error:")

    finally:
        close_program(ices_process)


def update_settings(settings_file):
    tree = ET.parse(settings_file)
    P = xmljson.Yahoo(dict_type = dict)
    for channel in tree.findall("channel"):
        id = channel.find("id").text
        d = P.data(channel)
        json_str = json.dumps(d)
        with open(f"/tmp/settings_{id}.txt", 'w') as f:
            f.write(json_str)

# start ices stream (CONSTANT)
ices_config_files = ['/srv/ftp/ices1.xml', '/srv/ftp/ices2.xml', '/srv/ftp/ices3.xml', '/srv/ftp/ices4.xml']
ices_processes = []
threads: List[threading.Thread] = []
settings_file = sys.argv[1]
settings_tree = ET.parse(settings_file)
for channel in settings_tree.findall("channel"):
    config_file = channel.find("config").text
    id = int(channel.find("id").text)
    logging.debug("Initializing IceS...")
    ices_process = subprocess.Popen(['ices', ices_config_files[id-1]],
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    time.sleep(3)
    logging.debug("IceS started.")
    ices_processes.append(ices_process)
    t = threading.Thread(target=radio, args=(config_file, ices_process, id))
    t.start()
    threads.append(t)
def close_programs(programs):
    for program in programs:
        close_program(program)

# set SIGTERM callback
signal.signal(signal.SIGTERM, lambda sig, frame: close_programs(ices_processes))

for t in threads:
    t.join()
