import datetime
import hashlib
import os
import subprocess
import threading

import dotenv
import flask
from flask import render_template, request, redirect
from tinydb import TinyDB, Query
from transmission_rpc import Client

dotenv.load_dotenv()

SERIES_TARGET = os.environ.get("SERIES_TARGET")
MOVIES_TARGET = os.environ.get("MOVIES_TARGET")
TRANSMISSION_URL = os.environ.get("TRANSMISSION_URL")
TRANSMISSION_USERNAME = os.environ.get("TRANSMISSION_USERNAME")
TRANSMISSION_PASSWORD = os.environ.get("TRANSMISSION_PASSWORD")

app = flask.Flask(__name__)
db = TinyDB("./files.json")

tc_client = Client(host=TRANSMISSION_URL,
                   username=TRANSMISSION_USERNAME,
                   password=TRANSMISSION_PASSWORD,
                   protocol="https",
                   port=443)


def hash_magnet_url(magnet_url):
    magnet_url = magnet_url.lower().split("&")[0]
    return hashlib.sha256(magnet_url.encode()).hexdigest()


def find_remote_torrent(magnet_hash):
    for remote_torrent in tc_client.get_torrents():
        if hash_magnet_url(remote_torrent.magnet_link) == magnet_hash:
            return remote_torrent
    return None


def move_download(local_torrent, remote_torrent):
    source_path = os.path.join(remote_torrent.download_dir, remote_torrent.name)

    if local_torrent["media_type"] == "series":
        target_path = os.path.join(SERIES_TARGET, local_torrent["target_location"])
    elif local_torrent["media_type"] == "movie":
        target_path = os.path.join(MOVIES_TARGET, local_torrent["target_location"])
    else:
        raise Exception("Invalid media type")

    try:
        subprocess.run(["rsync", "-av", source_path, target_path])
        print(f"Successfully moved {source_path} to {target_path}")
    except Exception as e:
        print(f"Failed moving {source_path} to {target_path}: {e}")


@app.route("/", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        query = Query()
        local_torrent = db.get(query.hash == request.form["hash"])
        remote_torrent = find_remote_torrent(magnet_hash=local_torrent["hash"])

        thread = threading.Thread(target=move_download, kwargs={
            "local_torrent": local_torrent,
            "remote_torrent": remote_torrent})
        thread.start()

        # Remove torrent from DB and transmission.
        db.remove(query.hash == request.form["hash"])
        tc_client.remove_torrent(ids=[remote_torrent.id], delete_data=False)

    local_torrents = db.all()
    remote_torrents_dict = {hash_magnet_url(t.magnet_link): t for t in tc_client.get_torrents()}

    for local_torrent in local_torrents:
        hashed_url = hash_magnet_url(local_torrent["url"])
        local_torrent["remote"] = remote_torrents_dict.get(hashed_url)
    return render_template("dashboard.html", torrents=local_torrents)


@app.route("/new", methods=["GET", "POST"])
def add_new():
    if request.method == "POST":
        media_type = request.form.get("media_type")
        url = request.form.get("url")
        target_location = request.form.get("target_location")

        # TODO: error catching
        tc_client.add_torrent(torrent=url)
        db.insert({
            "created_on": str(datetime.datetime.utcnow()),
            "media_type": media_type,
            "url": url,
            "target_location": target_location,
            "hash": hash_magnet_url(url)
        })
        return redirect("/")

    return render_template("add_new.html")
