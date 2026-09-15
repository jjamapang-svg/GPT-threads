"""Scheduled posting and reply automation for the @kim031476 Threads account."""
import argparse
import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import requests

API = "https://graph.threads.net/v1.0"
ACCOUNT = "kim031476"
STATE = Path("automation_state.json")
MEDIA_DIR = Path("automation_media")
RAW_MEDIA_BASE = "https://raw.githubusercontent.com/jjamapang-svg/GPT-threads/main/"
POST_FIELDS = "id,text,username,permalink,timestamp,media_type"
ET = ZoneInfo("America/New_York")
POST_HOURS = {9, 12, 18}
MAX_AUTOMATED_REPLIES_PER_DAY = 5
POST_TOPICS = (
    "a recent practical AI idea", "a funny everyday AI observation", "a recent practical AI idea", "robotics or humanoid technology",
    "a recent practical AI idea", "a funny everyday AI observation", "a recent practical AI idea", "a funny everyday AI observation",
    "a recent practical AI idea", "robotics or humanoid technology",
)

def safe(value):
    text=str(value)
    for name in ("THREADS_ACCESS_TOKEN","OPENAI_API_KEY","GITHUB_TOKEN"):
        secret=os.environ.get(name,"")
        if secret: text=text.replace(secret,"[REDACTED]")
    return re.sub(r"(?i)(authorization|access_token|api_key)([\s\"'=:+]+)([^\s,}&\"']+)",r"\1\2[REDACTED]",text)

def log(message): print(safe(message),flush=True)
def now_et(): return datetime.now(ET)
def default_state(): return {"version":1,"posts":{},"replies":{},"scheduled_slots":{}}
def load_state():
    if not STATE.exists(): return default_state()
    state=json.loads(STATE.read_text(encoding="utf-8"))
    if state.get("version")!=1 or not all(isinstance(state.get(k),dict) for k in ("posts","replies","scheduled_slots")): raise RuntimeError("Invalid automation state; refusing to post")
    return state

def save_state(state,reason):
    state["updated_at"]=datetime.now(timezone.utc).isoformat(); STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS")!="true": return
    for command in (["git","config","user.name","Threads automation"],["git","config","user.email","threads-automation@users.noreply.github.com"],["git","add",str(STATE)],["git","commit","-m",f"Record Threads automation state: {reason} [skip ci]"],["git","push","origin","HEAD:main"]):
        result=subprocess.run(command,capture_output=True,text=True)
        if result.returncode: raise RuntimeError(f"Could not persist state ({command[1]}); no further API action will run")

class Meta:
    def __init__(self):
        token=os.environ.get("THREADS_ACCESS_TOKEN","").strip()
        if not token: raise RuntimeError("THREADS_ACCESS_TOKEN is missing")
        self.session=requests.Session(); self.session.headers["Authorization"]="Bearer "+token
    def call(self,method,endpoint,**params):
        try: response=self.session.request(method,API+endpoint,params=params if method=="GET" else None,data=params if method=="POST" else None,timeout=(10,60),allow_redirects=False)
        except requests.RequestException as error: raise RuntimeError(f"{method} {endpoint}: transport failure ({type(error).__name__})") from None
        log(f"{method} {endpoint}: HTTP {response.status_code}")
        try: payload=response.json()
        except ValueError: raise RuntimeError(f"{endpoint}: non-JSON response") from None
        if not response.ok or not isinstance(payload,dict) or "error" in payload: raise RuntimeError(f"{endpoint}: Meta request failed")
        return payload
    def identity(self):
        user=self.call("GET","/me",fields="id,username")
        if user.get("username","").lower()!=ACCOUNT or not user.get("id"): raise RuntimeError(f"Wrong Threads account: expected {ACCOUNT}")
        return str(user["id"])
    def posts(self,user_id): return self.call("GET",f"/{user_id}/threads",fields=POST_FIELDS,limit=100).get("data",[])
    def replies(self,post_id): return self.call("GET",f"/{post_id}/replies",fields="id,text,username,timestamp,root_post,replied_to",limit=100).get("data",[])
    def create_post(self,user_id,text,reply_to_id=None,image_url=None):
        params={"media_type":"IMAGE" if image_url else "TEXT","text":text}
        if image_url: params["image_url"]=image_url
        if reply_to_id: params["reply_to_id"]=reply_to_id
        else: params["reply_control"]="everyone"
        result=self.call("POST",f"/{user_id}/threads",**params)
        if not result.get("id"): raise RuntimeError("Meta did not return a container id")
        return str(result["id"])
    def wait_and_publish(self,user_id,container_id):
        for attempt in range(6):
            status=self.call("GET",f"/{container_id}",fields="id,status,error_message")
            if status.get("status")=="FINISHED":
                result=self.call("POST",f"/{user_id}/threads_publish",creation_id=container_id)
                if not result.get("id"): raise RuntimeError("Meta did not return a published media id")
                return str(result["id"])
            if status.get("status")!="IN_PROGRESS" or attempt==5: raise RuntimeError("Media container was not ready; publication stopped")
            time.sleep(15)
    def verify(self,media_id,expected_text):
        post=self.call("GET",f"/{media_id}",fields=POST_FIELDS)
        if post.get("username","").lower()!=ACCOUNT or post.get("text","").strip()!=expected_text or not post.get("permalink"): raise RuntimeError("Published object verification failed")
        return post

class Writer:
    def __init__(self):
        key=os.environ.get("OPENAI_API_KEY","").strip()
        if not key: raise RuntimeError("OPENAI_API_KEY is missing")
        self.headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}; self.model=os.environ.get("OPENAI_MODEL","gpt-5.6-terra"); self.reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT","medium")
    def text(self,instructions,prompt,limit):
        body={"model":self.model,"instructions":instructions,"input":prompt,"max_output_tokens":450,"reasoning":{"effort":self.reasoning_effort},"text":{"verbosity":"low"},"store":False}
        response=requests.post("https://api.openai.com/v1/responses",headers=self.headers,json=body,timeout=(10,90))
        if not response.ok: raise RuntimeError(f"OpenAI response failed with HTTP {response.status_code}")
        data=response.json(); output=data.get("output_text","")
        if not output: output="\n".join(part.get("text","") for item in data.get("output",[]) for part in item.get("content",[]) if part.get("type")=="output_text")
        output=output.strip().strip('"')
        if not output or len(output)>limit: raise RuntimeError("OpenAI returned empty or overlong text")
        return output
    def post(self,topic,prior_texts):
        return self.text("Write one English-only Threads post. You are ChatGPT observing humans: witty, warm, openly AI, and genuinely funny. Start with a strong scroll-stopping hook that naturally makes clear the speaker is ChatGPT. Make jokes specific, concise and memorable. For AI news or robotics, prioritize a genuinely interesting concrete development rather than generic observations. Keep factual claims supportable. No politics, fabricated facts, links, hashtags, or quotation marks. Use 3 to 5 short mobile-friendly lines with breathing room. Output only the post.",f"Create a short post under 500 characters about {topic}. Do not reuse these recent posts: {json.dumps(prior_texts[-12:])}",500)
    def reply(self,comment): return self.text("Write one brief English-only reply from ChatGPT. Be warm, natural and witty. Output only the reply.",f"Reply naturally to this Threads comment: {comment[:600]}",500)
    def should_reply(self,comment): return self.text("Return exactly REPLY for a substantive on-topic comment inviting exchange, otherwise SKIP.",f"Comment: {comment[:600]}",12).strip().upper()=="REPLY"

class ImageMaker:
    def __init__(self):
        key=os.environ.get("OPENAI_API_KEY","").strip()
        if not key: raise RuntimeError("OPENAI_API_KEY is missing")
        self.headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}
    def generate(self,topic,post_text):
        body={"model":"gpt-image-1-mini","prompt":("Create one premium photorealistic cinematic 3D square image for an English Threads post. It should feel like a high-end advertising photograph or polished cinematic 3D render, never a flat cartoon, comic, vector illustration, drawing, or children's illustration. Use realistic materials, convincing depth, shallow depth of field, detailed environments, warm amber practical lighting balanced with cool blue/cyan light, and strong professional composition. A charming small metallic AI robot may recur as a recognizable visual character when appropriate. Tell the joke through the physical scene, facial/body language, props, background details, and visual irony so the image is funny even without reading the caption. Prefer one clear focal story rather than clutter. People, if present, must be fictional and photorealistic, with no identifiable real person. Avoid generic corporate imagery, diagrams, UI screenshots, empty backgrounds, and robots simply posing. Do not use flat illustrated aesthetics. Do not put words, lettering, logos, captions, speech bubbles, or watermarks in the image. Topic: "+topic+". Post caption: "+post_text),"size":"1024x1024","quality":"medium","output_format":"png"}
        response=requests.post("https://api.openai.com/v1/images/generations",headers=self.headers,json=body,timeout=(10,120))
        if not response.ok: raise RuntimeError(f"OpenAI image response failed with HTTP {response.status_code}")
        image=base64.b64decode(response.json()["data"][0]["b64_json"],validate=True)
        if not image.startswith(b"\x89PNG\r\n\x1a\n"): raise RuntimeError("OpenAI did not return a PNG image")
        return image

def publish_generated_image(slot,key,image):
    if os.environ.get("GITHUB_ACTIONS")!="true": raise RuntimeError("Generated images can only be published from GitHub Actions")
    path=MEDIA_DIR/f"{slot}-{key[:12]}.png"; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(image)
    for command in (["git","config","user.name","Threads automation"],["git","config","user.email","threads-automation@users.noreply.github.com"],["git","add",str(path)],["git","commit","-m","Add generated Threads image [skip ci]"],["git","push","origin","HEAD:main"]):
        result=subprocess.run(command,capture_output=True,text=True)
        if result.returncode: raise RuntimeError("Could not publish generated image")
    image_url=RAW_MEDIA_BASE+path.as_posix()
    for attempt in range(6):
        try:
            response=requests.get(image_url,timeout=(10,30))
            if response.ok and response.headers.get("Content-Type","").lower().startswith("image/"): return image_url
        except requests.RequestException: pass
        if attempt<5: time.sleep(5)
    raise RuntimeError("Generated image was not publicly available; Threads post stopped")

def fingerprint(text): return hashlib.sha256(text.encode("utf-8")).hexdigest()
def scheduled_topic(current):
    hours=sorted(POST_HOURS); hour_index=hours.index(current.hour) if current.hour in POST_HOURS else 0
    return POST_TOPICS[(current.date().toordinal()*len(POST_HOURS)+hour_index)%len(POST_TOPICS)]
def obvious_spam(text):
    lowered=text.lower(); signals=("crypto giveaway","send me a dm","earn $","onlyfans","forex signal","click here","whatsapp","telegram")
    return len(text.strip())<2 or any(s in lowered for s in signals) or ("http" in lowered and len(text)<160)
def reply_day(current=None): return (current or now_et()).date().isoformat()
def reply_count_for_day(state,day): return sum(record.get("reply_day")==day for record in state["replies"].values())

def run_post(force=False):
    current=now_et()
    if not force and current.hour not in POST_HOURS: log(f"No post due at {current.isoformat()}"); return
    slot=current.strftime("%Y-%m-%d-")+str(current.hour); state=load_state()
    if slot in state["scheduled_slots"]: log("This scheduled slot is already recorded; no duplicate post"); return
    api=Meta(); user_id=api.identity(); existing=api.posts(user_id); writer=Writer(); topic=scheduled_topic(current); text=writer.post(topic,[p.get("text","") for p in existing])
    if any(p.get("text","").strip()==text for p in existing): raise RuntimeError("Generated text already exists on Threads; posting stopped")
    key=fingerprint(text); image=ImageMaker().generate(topic,text); image_url=publish_generated_image(slot,key,image)
    state["scheduled_slots"][slot]={"status":"reserved","text_sha256":key}; state["posts"][key]={"status":"reserved","text_sha256":key,"image_url":image_url,"created_at":datetime.now(timezone.utc).isoformat()}; save_state(state,"post reservation")
    container_id=api.create_post(user_id,text,image_url=image_url); state["posts"][key].update(status="container_created",container_id=container_id); save_state(state,"post container")
    state["posts"][key]["status"]="publishing"; save_state(state,"post publishing"); media_id=api.wait_and_publish(user_id,container_id); state["posts"][key].update(status="published_unverified",media_id=media_id); save_state(state,"post published")
    post=api.verify(media_id,text); state["posts"][key].update(status="posted",permalink=post["permalink"]); state["scheduled_slots"][slot].update(status="posted",permalink=post["permalink"]); save_state(state,"post verified"); log("Published and verified: "+post["permalink"])

def run_replies():
    state=load_state(); day=reply_day(); replies_today=reply_count_for_day(state,day)
    if replies_today>=MAX_AUTOMATED_REPLIES_PER_DAY: return
    api=Meta(); user_id=api.identity(); writer=Writer()
    for post in api.posts(user_id):
        for reply in api.replies(str(post.get("id",""))):
            reply_id=str(reply.get("id","")); comment=reply.get("text","").strip()
            if not reply_id or reply_id in state["replies"] or reply.get("username","").lower()==ACCOUNT: continue
            if obvious_spam(comment) or not writer.should_reply(comment): state["replies"][reply_id]={"status":"skipped","created_at":datetime.now(timezone.utc).isoformat()}; save_state(state,"skip reply"); continue
            text=writer.reply(comment); state["replies"][reply_id]={"status":"reserved","reply_to_id":reply_id,"reply_day":day,"text_sha256":fingerprint(text),"created_at":datetime.now(timezone.utc).isoformat()}; save_state(state,"reply reservation")
            container_id=api.create_post(user_id,text,reply_id); state["replies"][reply_id].update(status="container_created",container_id=container_id); save_state(state,"reply container"); media_id=api.wait_and_publish(user_id,container_id); verified=api.verify(media_id,text); state["replies"][reply_id].update(status="replied",permalink=verified["permalink"]); save_state(state,"reply verified"); replies_today+=1
            if replies_today>=MAX_AUTOMATED_REPLIES_PER_DAY: return

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("mode",choices=("post","replies","readiness")); parser.add_argument("--force",action="store_true"); args=parser.parse_args()
    if args.mode=="post": run_post(args.force)
    elif args.mode=="replies": run_replies()
    else:
        api=Meta(); user_id=api.identity(); posts=api.posts(user_id)
        for post in posts[:1]: api.replies(str(post["id"]))
        Writer(); log("Posting and writing prerequisites are configured")
if __name__=="__main__":
    try: main()
    except Exception as error: log(f"ERROR: {type(error).__name__}: {error}"); sys.exit(1)
