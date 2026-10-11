import { create } from "zustand";
import { emptyTimeline, type Timeline } from "./studio-types";

type History = {past: Timeline[]; future: Timeline[]};
type State = {timeline: Timeline; selected: string|null; time: number; playing: boolean; zoom: number; dirty: boolean; history: History;
  load: (timeline: Timeline) => void; edit: (timeline: Timeline) => void; undo: () => void; redo: () => void; select: (id: string|null) => void; seek: (time: number) => void; play: (value: boolean) => void; setZoom: (value: number) => void; reset: () => void};
export const useStudio = create<State>((set) => ({timeline:emptyTimeline, selected:null,time:0,playing:false,zoom:1,dirty:false,history:{past:[],future:[]},
  load: timeline => set({timeline,dirty:false,history:{past:[],future:[]},selected:null,time:0,playing:false}),
  edit: timeline => set(state => ({timeline,dirty:true,history:{past:[...state.history.past.slice(-29),state.timeline],future:[]}})),
  undo: () => set(state => {const previous=state.history.past.at(-1);return previous?{timeline:previous,dirty:true,history:{past:state.history.past.slice(0,-1),future:[state.timeline,...state.history.future]}}:{};}),
  redo: () => set(state => {const next=state.history.future[0];return next?{timeline:next,dirty:true,history:{past:[...state.history.past,state.timeline],future:state.history.future.slice(1)}}:{};}),
  select: selected=>set({selected}), seek: time=>set(state=>({time:Math.max(0,Math.min(state.timeline.duration_seconds,time))})), play: playing=>set({playing}), setZoom: zoom=>set({zoom}),
  reset: ()=>set({timeline:emptyTimeline,selected:null,time:0,playing:false,zoom:1,dirty:false,history:{past:[],future:[]}}),
}));
