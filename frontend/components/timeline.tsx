"use client";
import { useRef } from "react";
import { Eye, EyeOff, Music2, Type, Film, Image as ImageIcon, ZoomIn, ZoomOut, Undo2, Redo2, Trash2 } from "lucide-react";
import { useStudio } from "../lib/studio-store";
import type { Clip } from "../lib/studio-types";

export function TimelineEditor() {
  const s=useStudio(); const ruler=useRef<HTMLDivElement>(null);
  const tracks=Array.from(new Set([0,1,2,...s.timeline.clips.map(c=>c.track)])).sort((a,b)=>a-b);
  const width=Math.max(600,s.timeline.duration_seconds*55*s.zoom);
  const ticks=Array.from({length:Math.ceil(s.timeline.duration_seconds)+1},(_,i)=>i);
  function change(id:string,delta:Partial<Clip>) {s.edit({...s.timeline,clips:s.timeline.clips.map(c=>c.id===id?{...c,...delta}:c)});}
  function drag(event:React.PointerEvent<HTMLButtonElement>,clip:Clip) {
    if((event.target as HTMLElement).closest(".clip-hide")) return;
    s.select(clip.id);event.currentTarget.setPointerCapture(event.pointerId);
    const initialX=event.clientX, initial=clip.start;let start=initial;
    const button=event.currentTarget;
    const move=(e:PointerEvent)=>{start=Math.max(0,Math.min(s.timeline.duration_seconds-clip.duration,Math.round((initial+(e.clientX-initialX)/width*s.timeline.duration_seconds)*24)/24));button.style.left=`${start/s.timeline.duration_seconds*100}%`;};
    const finish=()=>{button.removeEventListener("pointermove",move);button.removeEventListener("pointerup",finish);button.removeEventListener("pointercancel",finish);if(start!==initial)change(clip.id,{start});};
    button.addEventListener("pointermove",move);button.addEventListener("pointerup",finish);button.addEventListener("pointercancel",finish);
  }
  return <section className="timeline-panel" aria-label="Composition timeline">
    <div className="timeline-toolbar"><strong><Film size={14}/> Timeline <span>{s.timeline.fps} FPS</span></strong><div>
      <button title="Undo" disabled={!s.history.past.length} onClick={s.undo}><Undo2 size={15}/></button><button title="Redo" disabled={!s.history.future.length} onClick={s.redo}><Redo2 size={15}/></button>
      <button title="Zoom out" onClick={()=>s.setZoom(Math.max(.5,s.zoom-.25))}><ZoomOut size={15}/></button><span>{Math.round(s.zoom*100)}%</span><button title="Zoom in" onClick={()=>s.setZoom(Math.min(4,s.zoom+.25))}><ZoomIn size={15}/></button>
    </div></div>
    <div className="timeline-scroll"><div style={{width:width+112}}>
      <div className="ruler" ref={ruler} style={{width,marginLeft:112}} onPointerDown={e=>{const bounds=e.currentTarget.getBoundingClientRect();s.seek((e.clientX-bounds.left)/bounds.width*s.timeline.duration_seconds);}}>
        {ticks.map(i=><span key={i} style={{left:`${i/s.timeline.duration_seconds*100}%`}}>{String(Math.floor(i/60)).padStart(2,"0")}:{String(i%60).padStart(2,"0")}</span>)}
      </div>
      {tracks.map(track=><div className="track" key={track}><div className="track-label">{track===0?<Film size={14}/>:track===1?<Music2 size={14}/>:<Type size={14}/>} {track===0?"Picture":track===1?"Audio":track===2?"Titles":`Layer ${track}`}</div><div className="track-lane" style={{width}}>
        {s.timeline.clips.filter(c=>c.track===track).map(clip=><button key={clip.id} className={`timeline-clip ${clip.kind} ${s.selected===clip.id?"selected":""} ${clip.hidden?"hidden":""}`} style={{left:`${clip.start/s.timeline.duration_seconds*100}%`,width:`${clip.duration/s.timeline.duration_seconds*100}%`}} onPointerDown={e=>drag(e,clip)} onClick={()=>s.select(clip.id)} aria-label={`Select ${clip.kind} clip ${clip.text||clip.id}`}>
          {clip.kind==="audio"?<Music2 size={13}/>:clip.kind==="text"?<Type size={13}/>:clip.kind==="image"?<ImageIcon size={13}/>:<Film size={13}/>}<span>{clip.text||clip.id}</span>
        </button>)}
        <div className="playhead" style={{left:`${s.time/s.timeline.duration_seconds*100}%`}}/>
      </div></div>)}
    </div></div>
    <div className="timeline-bottom"><span>Drag to move · Select to edit · Snap: 1 frame</span><span>{s.timeline.clips.length} clips · {s.timeline.duration_seconds.toFixed(1)}s</span></div>
  </section>;
}

export function ClipInspector() {
  const s=useStudio();const clip=s.timeline.clips.find(c=>c.id===s.selected);
  function change(delta:Partial<Clip>) {if(clip)s.edit({...s.timeline,clips:s.timeline.clips.map(c=>c.id===clip.id?{...c,...delta}:c)});}
  if(!clip)return <div className="inspector-empty"><Type size={24}/><h3>Make it yours</h3><p>Select a clip to edit its timing, copy, or sound.</p></div>;
  return <div className="clip-inspector"><div className="panel-title"><strong>{clip.kind.toUpperCase()} CLIP</strong><button title="Delete clip" onClick={()=>{s.edit({...s.timeline,clips:s.timeline.clips.filter(c=>c.id!==clip.id)});s.select(null);}}><Trash2 size={15}/></button></div>
    <label>Clip name<input value={clip.id} readOnly/></label>
    {clip.kind==="text"&&<label>On-screen copy<textarea maxLength={240} value={clip.text} onChange={e=>change({text:e.target.value})}/></label>}
    <div className="field-pair"><label>Start (s)<input type="number" step={1/24} min={0} max={s.timeline.duration_seconds-clip.duration} value={clip.start} onChange={e=>change({start:Math.max(0,Math.min(s.timeline.duration_seconds-clip.duration,Number(e.target.value)))})}/></label>
    <label>Duration (s)<input type="number" step={1/24} min={1/24} max={s.timeline.duration_seconds-clip.start} value={clip.duration} onChange={e=>change({duration:Math.max(1/24,Math.min(s.timeline.duration_seconds-clip.start,Number(e.target.value)))})}/></label></div>
    {clip.artifact_id&&<label>Source in (s)<input type="number" step={1/24} min={0} value={clip.source_in} onChange={e=>change({source_in:Math.max(0,Number(e.target.value))})}/></label>}
    {(clip.kind==="audio"||clip.kind==="video")&&<><label>Volume {Math.round(clip.volume*100)}%<input type="range" min={0} max={1} step={.01} value={clip.volume} onChange={e=>change({volume:Number(e.target.value)})}/></label>
    {clip.kind==="audio"&&<div className="field-pair"><label>Fade in<input type="number" min={0} max={5} step={.1} value={clip.fade_in} onChange={e=>change({fade_in:Number(e.target.value)})}/></label><label>Fade out<input type="number" min={0} max={5} step={.1} value={clip.fade_out} onChange={e=>change({fade_out:Number(e.target.value)})}/></label></div>}</>}
    <button className="secondary" onClick={()=>change({hidden:!clip.hidden})}>{clip.hidden?<Eye size={14}/>:<EyeOff size={14}/>} {clip.hidden?"Show clip":"Hide clip"}</button>
    {clip.artifact_id&&<small className="mono">{clip.artifact_id}</small>}
  </div>;
}
