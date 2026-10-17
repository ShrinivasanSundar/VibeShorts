"use client";
import { useEffect, useRef, useState } from "react";
import { Play, Pause, Maximize2 } from "lucide-react";
import { Brand } from "./brand";
import { useStudio } from "../lib/studio-store";
import { call } from "../lib/api";
import { claimPlayback } from "./private-media";
import { Reel } from "./loading-state";

type Player = HTMLElement & {play:()=>void;pause:()=>void;seek:(time:number)=>void;currentTime:number;srcdoc:string;iframeElement?:HTMLIFrameElement};
export function CompositionPreview({projectId,artifactId,independent=false}:{projectId:string;artifactId:string|null;independent?:boolean}) {
  const container=useRef<HTMLDivElement>(null);const player=useRef<Player|null>(null);const studio=useStudio();const [error,setError]=useState("");const [ready,setReady]=useState(false);
  const [localTime,setLocalTime]=useState(0);const [localPlaying,setLocalPlaying]=useState(false);
  const [profile,setProfile]=useState({aspect_ratio:"9:16",duration_seconds:15});
  const s=independent?{time:localTime,playing:localPlaying,play:setLocalPlaying,seek:setLocalTime,timeline:profile,dirty:false}:studio;
  useEffect(()=>{let active=true;setError("");setReady(false);
    async function load(){if(!artifactId)return;try{
      await import("@hyperframes/player");
      const response=await call(`/v1/projects/${projectId}/compositions/${artifactId}/preview`);
      if(!active||!container.current)return;
      setProfile({aspect_ratio:response.data.profile.width>response.data.profile.height?"16:9":"9:16",duration_seconds:response.data.profile.duration_seconds});setLocalTime(0);setLocalPlaying(false);
      const element=document.createElement("hyperframes-player") as Player;
      element.setAttribute("sandbox-origin","opaque");element.setAttribute("width",String(response.data.profile.width));element.setAttribute("height",String(response.data.profile.height));
      element.setAttribute("srcdoc",response.data.html);
      element.style.width="100%";element.style.height="100%";
      element.addEventListener("ready",()=>active&&setReady(true));
      element.addEventListener("error",()=>active&&setError("Preview could not be loaded. Try the draft export."));
      element.addEventListener("timeupdate",()=>{if(active){if(independent)setLocalTime(element.currentTime);else useStudio.getState().seek(element.currentTime);}});
      element.addEventListener("ended",()=>independent?setLocalPlaying(false):useStudio.getState().play(false));
      container.current.replaceChildren(element);player.current=element;
    }catch(e){if(active)setError((e as Error).message);}}
    void load();return()=>{active=false;player.current?.pause();container.current?.replaceChildren();player.current=null;};
  },[projectId,artifactId,independent]);
  useEffect(()=>{const pause=(event:Event)=>{if((event as CustomEvent).detail!==player.current){player.current?.pause();if(independent)setLocalPlaying(false);else useStudio.getState().play(false);}};window.addEventListener("vibeshorts:play",pause);return()=>window.removeEventListener("vibeshorts:play",pause);},[independent]);
  useEffect(()=>{if(s.playing&&player.current){claimPlayback(player.current);player.current.play();}else player.current?.pause();},[s.playing]);
  useEffect(()=>{if(player.current&&!s.playing)player.current.seek(s.time);},[s.time,s.playing]);
  return <section className="preview-area"><div className="preview-mat"><div className={`preview-canvas ${s.timeline.aspect_ratio==="16:9"?"landscape":""}`} ref={container}/>
    {!artifactId&&<div className="preview-placeholder"><span className="preview-symbol"><Brand compact /></span><span className="eyebrow preview-eyebrow">THINK IT. MAKE IT MOVE.</span><h2>Your story, in motion.</h2><p>Start with a brief, or build your own cut.<br/>Your composition will appear here.</p><div className="preview-grid"/></div>}
    {artifactId&&!ready&&!error&&<div className="preview-loading" role="status"><Reel /><span>Loading your video preview…</span></div>}
    {error&&<p className="error">{error}</p>}
  </div><div className="transport"><button title={s.playing?"Pause":"Play"} disabled={!artifactId||!ready} onClick={()=>s.play(!s.playing)}>{s.playing?<Pause size={18}/>:<Play size={18}/>}</button>
    <span className="timecode">{s.time.toFixed(2).padStart(5,"0")} <em>/ {s.timeline.duration_seconds.toFixed(2)}</em></span><input aria-label="Scrub preview" type="range" min={0} max={s.timeline.duration_seconds} step={1/24} value={s.time} onChange={e=>{s.play(false);s.seek(Number(e.target.value));}}/>
    <span className="canvas-size">{s.timeline.aspect_ratio} · 720p</span><button title="Fullscreen preview" onClick={()=>container.current?.requestFullscreen()}><Maximize2 size={15}/></button></div>
    {s.dirty&&<p className="preview-notice">Unsaved timeline edits. Save a revision to update this preview.</p>}
  </section>;
}
