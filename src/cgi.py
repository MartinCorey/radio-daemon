from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse
from starlette.middleware.cors import CORSMiddleware
import imghdr
import datetime
import time

DAEMON_DIR = "/home/elaine/app/source_daemon"

app = FastAPI()

app.add_middleware(
CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

@app.get("/metadata/{channel}")
async def get_metadata(channel: str):
    with open(f"/tmp/metadata_{channel}.txt", "r") as f:
        m = f.read()
        return dict([tuple(l.split('=')) for l in m.split('\n')])

@app.get("/albumimage/{channel}",
    response_class=Response,
)
async def get_album_image(channel: str):
    headers = {"Cache-Control": "no-store"}
    file_path = f"/tmp/current_album_{channel}"
    image_type = imghdr.what(file_path)
    with open(file_path, "rb") as f:
        return Response(content=f.read(), media_type=f"image/{image_type}", headers=headers)

@app.get("/blockimage/{channel}",
    response_class=Response,
)
async def get_block_image(channel: str):
    headers = {"Cache-Control": "no-store"}
    file_path = f"/tmp/current_block_{channel}"
    image_type = imghdr.what(file_path)
    with open(file_path, "rb") as f:
        return Response(content=f.read(), media_type=f"image/{image_type}", headers=headers)

@app.get("/segmentimage/{channel}",
    response_class=Response,
)
async def get_segment_image(channel: str):
    headers = {"Cache-Control": "no-store"}
    file_path = f"/tmp/current_segment_{channel}"
    image_type = imghdr.what(file_path)
    with open(file_path, "rb") as f:
        return Response(content=f.read(), media_type=f"image/{image_type}", headers=headers)


@app.get("/metadata/{channel}")
async def get_metadata(channel: str):
    with open(f"/tmp/metadata_{channel}.txt", "r") as f:
        m = f.read()
        return dict([tuple(l.split('=')) for l in m.split('\n')])

@app.get("/position/{channel}")
async def get_metadata(channel: str):
    with open(f"/tmp/metadata_{channel}.txt", "r") as f:
        m = f.read()
        return time.time() - float(dict([tuple(l.split('=')) for l in m.split('\n')]).get("starttime"))


@app.get("/settings/{channel}")
async def get_settings(channel: str):
    with open(f"/tmp/settings_{channel}.txt", "r") as f:
        return f.read()



@app.get("/time",
    response_class=PlainTextResponse
)
async def get_time():
    return str(datetime.datetime.now(datetime.timezone.utc))
