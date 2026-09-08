import os
import sys
import uuid
import shutil
import random
import subprocess
import json
import whisper
import time
import shlex
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from io import BytesIO
from pydub import AudioSegment
from datetime import datetime

def reset_workspace():
    os.makedirs("workspaces", exist_ok=True)
    shutil.rmtree("workspaces")
    os.makedirs("workspaces", exist_ok=True)

def length(video, file):
    if os.path.exists(os.path.join(video.workspace, os.path.basename(file))):
        return float(json.loads(subprocess.run(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","json",os.path.join(video.workspace, os.path.basename(file))],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        ).stdout)["format"]["duration"])

def path(p: str) -> str:
    normalized = os.path.normpath(p)
    if sys.platform.startswith("win"):
        return normalized.replace("/", "\\")
    else:
        return normalized.replace("\\", "/")


class Database:
    def __init__(self, dbpath):
        self.path = path(dbpath)
        self.files = os.listdir(self.path)

    def clear(self):
        for file in self.files:
            os.remove(os.path.join(self.path, file))

class Video:
    def __init__(self):
        self.files = []
        self.workspace = path(f"workspaces\\mpy_{str(uuid.uuid4())[:8]}")
        self.cpu_fraction = 1
        os.makedirs(self.workspace)

    def cap_cpu(self, cap):
        """
        Cap between 0 and 1
        """
        self.cpu_fraction = cap

    def run_ffmpeg(self, command, print=False):

        cpu_fraction = self.cpu_fraction
        cpu_fraction = max(0.0, min(1.0, cpu_fraction))

        cores = os.cpu_count() or 1
        threads = max(1, int(cores * cpu_fraction))

        is_list = isinstance(command, (list, tuple))

        cmd_list = list(command) if is_list else shlex.split(command)

        if "-threads" not in cmd_list:
            cmd_list = ["ffmpeg", "-threads", str(threads)] + cmd_list[1:]

        subprocess.run(
            cmd_list,
            stdout=None if print else subprocess.DEVNULL,
            stderr=None if print else subprocess.DEVNULL,
            check=True
        )

    def populate(self, source):
        if isinstance(source, Database):
            folder = source.path
            files = source.files
        elif isinstance(source, Video):
            folder = source.workspace
            files = source.files
        else:
            folder = source
            files = os.listdir(folder)

        # copy files into this workspace
        for f in files:
            shutil.copy2(os.path.join(folder, f), os.path.join(self.workspace, f))
        self.files = files.copy()

    def export(self, folder = path("storage\\exports")):
        if isinstance(folder, Database):
            folder = folder.path
        os.makedirs(folder, exist_ok=True)
        for file in self.files:
            shutil.copy2(os.path.join(self.workspace, file), os.path.join(folder, f"{str(uuid.uuid4())[:8]}_{file}"))

    def close(self):
        shutil.rmtree(self.workspace)
    
    def remove(self, file):
        os.remove(os.path.join(self.workspace, file))

    def pick(self, count = 1):
        newpaths = self.files.copy()
        random.shuffle(newpaths)
        newpaths = newpaths[:count]
        for file in self.files:
            if file not in newpaths:
                self.remove(file)
        self.files = newpaths

    def split(self, time):
        newpaths = []
        for file in self.files:
            src = os.path.join(self.workspace, file)
            name, ext = os.path.splitext(file)
            parts = [f"{name}_split_a{ext}", f"{name}_split_b{ext}"]
            self.run_ffmpeg(["ffmpeg","-y","-i",src,"-t",str(time),"-c:v","libx264","-c:a","aac",os.path.join(self.workspace,parts[0])])
            self.run_ffmpeg(["ffmpeg","-y","-i",src,"-ss",str(time),"-c:v","libx264","-c:a","aac",os.path.join(self.workspace,parts[1])])
            newpaths.extend(parts)
            self.remove(file)
        self.files = newpaths

    def speed(self, factor):
        # Makes speed chains to have speeds in ranges > 2 and less than 0.5
        def atempo_chain(f):
            chain = []
            while f < 0.5 or f > 2.0:
                next_f = 2.0 if f > 2.0 else 0.5
                chain.append(next_f)
                f /= next_f
            chain.append(f)
            return ",".join(f"atempo={round(x,3)}" for x in chain)
        
        # Makes sure the video has audio to prevent errors
        def has_audio(f): 
            info = json.loads(subprocess.run(["ffprobe","-v","error","-show_entries","stream=codec_type","-of","json",os.path.join(self.workspace,f)], stdout=subprocess.PIPE, text=True).stdout)
            return any(s.get("codec_type")=="audio" for s in info.get("streams",[]))

        newpaths = []
        for f in self.files:
            src = os.path.join(self.workspace, f)
            name, ext = os.path.splitext(f)
            out = f"{name}_speed-{factor}x{ext}"
            vf = f"[0:v]setpts={round(1/factor,3)}*PTS[v]"
            if has_audio(f):
                af = atempo_chain(factor)
                fc = f"{vf};[0:a]{af}[a]"
                maps = ["-map","[v]","-map","[a]"]
            else:
                fc = vf
                maps = ["-map","[v]"]
            self.run_ffmpeg(["ffmpeg","-y","-i",src,"-filter_complex",fc,*maps,"-c:v","libx264","-c:a","aac",os.path.join(self.workspace,out)])
            newpaths.append(out)
            self.remove(f)
        self.files = newpaths


    
    def segrnd(self, seconds):
        newpaths = []
        for f in self.files:
            if length(self, f) > seconds:
                start = random.random() * length(self, f) - seconds
                end = start + seconds
                src = os.path.join(self.workspace, f)
                name, ext = os.path.splitext(f)
                out = f"{name}_segment{ext}"
                self.run_ffmpeg(["ffmpeg","-y","-i",src,"-ss",str(start),"-t",str(end-start),"-c:v","libx264","-c:a","aac",os.path.join(self.workspace,out)])
                newpaths.append(out)
                self.remove(f)
            else:
                newpaths.append(f)
        self.files = newpaths

    def concat(self):
        if not self.files: return

        temp_files, list_file = [], os.path.join(self.workspace, "concat_list.txt")

        # Re-encode inputs to uniform format
        for i,f in enumerate(self.files):
            src = os.path.join(self.workspace,f)
            tmp = os.path.join(self.workspace,f"tmp_{i}.mp4")
            self.run_ffmpeg(["ffmpeg","-y","-i",src,"-c:v","libx264","-pix_fmt","yuv420p","-r","30","-c:a","aac","-ac","2","-ar","44100",tmp])
            temp_files.append(tmp)

        # Write concat list
        with open(list_file,"w",encoding="utf-8") as f:
            for tmp in temp_files:
                filename = os.path.basename(tmp).replace('\\','/')
                f.write(f"file '{filename}'\n")

        output_name="concat.mp4"
        out_path = os.path.join(self.workspace, output_name)
        self.run_ffmpeg(["ffmpeg","-y","-f","concat","-safe","0","-i",list_file,"-c:v","libx264","-c:a","aac",out_path])

        # Cleanup
        for f in self.files + temp_files: os.remove(os.path.join(self.workspace,os.path.basename(f)))
        os.remove(list_file)
        self.files = [output_name]

    def caption(self, font_path, text):

        def seconds_to_ass(sec: float) -> str:
            h, m = int(sec // 3600), int((sec % 3600) // 60)
            s, cs = int(sec % 60), int(round((sec - int(sec)) * 100))
            return f"{h}:{m:02}:{s:02}.{cs:02}"

        model = whisper.load_model("base")
        new_files = []

        for f in self.files:
            src = os.path.join(self.workspace, f)
            name, ext = os.path.splitext(f)
            out = f"{name}_subbed{ext}"

            try:
                # Enable word-level timestamps
                segments = model.transcribe(src, word_timestamps=True).get("segments", [])
            except Exception:
                new_files.append(f)
                continue
            if not segments:
                new_files.append(f)
                continue

            ass_lines = []

            for seg in segments:
                if "words" not in seg:
                    # fallback: treat full segment as single word
                    ass_lines.append((
                        seconds_to_ass(seg["start"]),
                        seconds_to_ass(seg["end"]),
                        seg["text"].strip()
                    ))
                    continue

                for w in seg["words"]:
                    word_text = w["word"].strip()
                    if not word_text:
                        continue
                    start_time = w["start"]
                    end_time = w["end"]
                    ass_lines.append((
                        seconds_to_ass(start_time),
                        seconds_to_ass(end_time),
                        word_text
                    ))

            if not ass_lines:
                new_files.append(f)
                continue

            # Generate ASS content
            ass_content = (
                "[Script Info]\nTitle: Subtitles\nScriptType: v4.00+\n\n"
                f"[V4+ Styles]\nStyle: Default,{font_path},13,&H00FFFFFF,&H000000FF,"
                "&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,2,5,10,10,10,6\n\n"
                "[Events]\n" +
                "\n".join(
                    f"Dialogue: 0,{s},{e},Default,,0,0,0,,{{\\fs13\\t(0,{int((float(e.split(':')[-1])-float(s.split(':')[-1]))*1000)},\\fs16)}}{t}"
                    for s, e, t in ass_lines
                )
            )

            ass_file = os.path.join(self.workspace, f"{name}.ass").replace("\\", "/")
            with open(ass_file, "w", encoding="utf-8") as out_file:
                out_file.write(ass_content)

            # Fully re-encode video with hardcoded subtitles
            out_path = os.path.join(self.workspace, out)
            self.run_ffmpeg([
                "ffmpeg", "-y", "-i", src, "-vf", f"ass={ass_file}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                "-c:a", "aac", "-ac", "2", "-ar", "44100", out_path
            ])

            self.remove(f)
            new_files.append(out)

        self.files = new_files

    def mute(self):
        """
        Removes all audio from every video in the workspace.
        Fully re-encodes video to ensure compatibility with ASS subtitles.
        """
        if not self.files:
            return

        new_files = []
        for f in self.files:
            src = os.path.join(self.workspace, f)
            name, ext = os.path.splitext(f)
            out_name = f"{name}_muted{ext}"
            out_path = os.path.join(self.workspace, out_name)

            # Re-encode video and remove audio
            self.run_ffmpeg([
                "ffmpeg", "-y", "-i", src,
                "-c:v", "libx264",     # re-encode video
                "-pix_fmt", "yuv420p", # safe pixel format
                "-r", "30",             # frame rate
                "-an",                  # remove all audio
                out_path
            ])

            self.remove(f)
            new_files.append(out_name)

        self.files = new_files


    def add_audio(self, audio):
        """
        Add or replace the audio of all video files in the workspace with the audio from an Audio instance.
        Audio is re-encoded to AAC to prevent corruption.
        """
        if not self.files:
            return
        import os

        new_files = []
        for f in self.files:
            src = os.path.join(self.workspace, f)
            name, ext = os.path.splitext(f)
            out = os.path.join(self.workspace, f"{name}_with_audio{ext}")

            self.run_ffmpeg([
                "ffmpeg", "-y", "-i", src, "-i", audio.path,
                "-c:v", "copy",           # copy video stream
                "-c:a", "aac",            # re-encode audio
                "-map", "0:v:0",          # take video from first input
                "-map", "1:a:0",          # take audio from audio instance
                out
            ])
            new_files.append(os.path.basename(out))
            self.remove(f)

        self.files = new_files


    def amplify(self, db: float):
        """Adjust audio volume of all videos in workspace by `db` decibels."""
        if not self.files: return
        new_files = []
        for f in self.files:
            src, name, ext = os.path.join(self.workspace, f), *os.path.splitext(f)
            out = os.path.join(self.workspace, f"{name}_vol{('+' if db>=0 else '')}{db}dB{ext}")
            self.run_ffmpeg([
                "ffmpeg", "-y", "-i", src,
                "-filter:a", f"volume={db}dB",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                out
            ])
            new_files.append(out)
            self.remove(f)
        self.files = new_files


class Audio:
    def __init__(self):
        self.path = ""
        self.workspace = path(f"workspaces\\mpy_{str(uuid.uuid4())[:8]}.wav")
    
    def populate(self, source):
        shutil.copy2(source, self.workspace)
        self.path = source

    def export(self, folder):
        if isinstance(folder, Database):
            folder = folder.path
        os.makedirs(folder, exist_ok=True)
        shutil.copy2(self.path, os.path.join(folder, os.path.basename(self.path)))

    def speed(self, factor):
        def atempo_chain(f):
            chain = []
            while f < 0.5 or f > 2.0:
                step = 2.0 if f > 2.0 else 0.5
                chain.append(step)
                f /= step
            chain.append(f)
            return ",".join(f"atempo={round(x, 3)}" for x in chain)

        src = self.path
        directory, filename = os.path.split(src)
        name, ext = os.path.splitext(filename)

        tmp_out = os.path.join(directory, f"{name}__tmp{ext}")

        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", src,
            "-filter:a", atempo_chain(factor),
            tmp_out
        ]

        subprocess.run(ffmpeg_cmd, check=True)

        os.replace(tmp_out, src)  # atomic overwrite on Windows
        self.path = src


    def tts(self, text):
        import requests, os, uuid, time
        from io import BytesIO

        # Load API key
        with open(path("secrets\\deepgrams.txt")) as f:
            api_key = f.read().strip()

        voice = "aura-2-arcas-en"
        url = f"https://api.deepgram.com/v1/speak?model={voice}"
        headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}

        # Split text into ~2500-char chunks without splitting words
        def split_text(t, limit=2500):
            words, chunks, chunk = t.split(), [], ""
            for w in words:
                if len(chunk) + len(w) + 1 > limit:
                    chunks.append(chunk.strip())
                    chunk = w
                else:
                    chunk += " " + w if chunk else w
            if chunk:
                chunks.append(chunk.strip())
            return chunks

        # Generate and combine audio chunks
        combined_audio = BytesIO()
        for chunk in split_text(text):
            st = time.time()
            for _ in range(5):  # retry loop in case of transient errors
                response = requests.post(url, headers=headers, json={"text": chunk})
                if response.status_code == 200:
                    combined_audio.write(response.content)
                    break
                elif response.status_code == 429:
                    raise RuntimeError("Rate limit reached")
                else:
                    time.sleep(0.5)  # small delay before retry
            else:
                raise RuntimeError(f"Failed to get audio for chunk: {chunk[:50]}...")

        # Save combined audio to workspace
        os.makedirs(os.path.dirname(self.workspace), exist_ok=True)
        with open(self.workspace, "wb") as f:
            f.write(combined_audio.getvalue())

        self.path = self.workspace

    def length(self):
        if not self.path or not os.path.exists(self.path):
            raise FileNotFoundError(f"Audio file not found at path: {self.path}")

        audio = AudioSegment.from_file(self.path)
        return len(audio) / 1000.0  # returns length in seconds

    def amplify(self, db: float):
        """
        Increase or decrease the audio volume by `db` decibels.
        Positive `db` increases volume, negative decreases.
        """
        from pydub import AudioSegment
        import os

        if not self.path or not os.path.exists(self.path):
            raise FileNotFoundError(f"Audio file not found at path: {self.path}")

        audio = AudioSegment.from_file(self.path)
        adjusted = audio + db  # pydub allows adding/subtracting decibels directly

        # Re-encode and overwrite the same path
        adjusted.export(self.path, format=os.path.splitext(self.path)[1][1:])

    def from_video(self, video):
        """
        Extract audio from the first video file in a Video instance.
        Saves it to self.workspace and updates self.path.
        """
        import os
        import subprocess

        if not video.files:
            raise FileNotFoundError("No files found in the Video instance.")

        src_video = os.path.join(video.workspace, video.files[0])
        os.makedirs(os.path.dirname(self.workspace), exist_ok=True)

        # Extract audio using ffmpeg, re-encoding to WAV
        subprocess.run([
            "ffmpeg", "-y", "-i", src_video,
            "-vn",                  # ignore video
            "-acodec", "pcm_s16le", # WAV format
            "-ar", "44100",         # 44.1 kHz
            "-ac", "2",             # stereo
            self.workspace
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self.path = self.workspace

    def close(self):
        os.remove(self.path)

class Channel:
    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    def __init__(self, name: str):
        self.name = name
        client_secret_path = path("secrets\\client_secret.json")
        self.client_secret_path = client_secret_path

        self.secret_dir = os.path.join("secrets", name)
        self.token_path = os.path.join(self.secret_dir, "token.pkl")

        # Folder exists → reuse data
        if os.path.exists(self.secret_dir):
            if not os.path.isdir(self.secret_dir):
                raise NotADirectoryError(f"{self.secret_dir} exists and is not a directory")
        else:
            # Folder does not exist → first-time setup
            os.makedirs(self.secret_dir)
            self.creds = None
            self.youtube = None
            self.verify()
            return

        self.creds: Credentials | None = None
        self.youtube = None

        self._load_token()

        # Folder exists but no token → force OAuth
        if self.creds is None:
            self.verify()
        # Folder + token → build client immediately
        else:
            self.youtube = build(
                "youtube",
                "v3",
                credentials=self.creds,
                cache_discovery=False,
            )

    def _load_token(self):
        if os.path.exists(self.token_path):
            with open(self.token_path, "rb") as f:
                self.creds = pickle.load(f)

    def _save_token(self):
        with open(self.token_path, "wb") as f:
            pickle.dump(self.creds, f)

    def verify(self):
        if self.creds and self.creds.valid:
            pass
        elif self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.client_secret_path,
                self.SCOPES,
            )
            self.creds = flow.run_local_server(port=0)

        self._save_token()
        self.youtube = build(
            "youtube",
            "v3",
            credentials=self.creds,
            cache_discovery=False,
        )
        return self.youtube

    def upload(
        self,
        video: Video,
        title: str,
        description: str,
        tags: list[str],
        category_id: str = "22",
        privacy_status: str = "public",
    ):
        # Ensure YouTube client exists
        if self.youtube is None:
            self.verify()

        # Ensure credentials are valid BEFORE upload
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            self._save_token()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        video_path = os.path.join(video.workspace, video.files[0])

        media = MediaFileUpload(
            video_path,
            mimetype="video/*",
            chunksize=8 * 1024 * 1024,  # 8 MB
            resumable=True,
        )

        request = self.youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        retries = 0
        max_retries = 10

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"{int(status.progress() * 100)}%")
            except (HttpError, OSError) as e:
                retries += 1
                if retries > max_retries:
                    raise

                time.sleep(min(2 ** retries, 32))

        return response

