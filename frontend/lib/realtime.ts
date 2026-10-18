import { getApp } from "firebase/app";
import { connectFirestoreEmulator, doc, getFirestore, onSnapshot } from "firebase/firestore";
let connected=false;
function database() {
  const db=getFirestore(getApp());
  if(!connected&&process.env.NEXT_PUBLIC_MODE!=="production") {
    const endpoint=new URL(`http://${process.env.NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST||"127.0.0.1:18080"}`);
    connectFirestoreEmulator(db,endpoint.hostname,Number(endpoint.port||"80"));connected=true;
  }
  return db;
}
export type RunActivity={job_id:string;status:string;updated_at:number};
// One small document per run holds its latest job step, so progress costs one read per change
// instead of the whole run_summaries collection on every subscribe and reconnect.
export function subscribeRunActivity(projectId:string,runId:string,onChange:(activity:RunActivity)=>void) {
  let first=true;
  return onSnapshot(doc(database(),"projects",projectId,"run_summaries",runId+"_activity"),snapshot=>{
    const data=snapshot.data() as RunActivity|undefined;
    if(first){first=false;return;} // The first snapshot repeats what the last fetch already showed.
    if(data)onChange(data);
  },()=>{/* Authenticated API polling remains the fallback. */});
}
// Scheduler leases rewrite the conversation document without changing what the user sees.
const LEASE_FIELDS=new Set(["lease_owner","lease_expiry"]);
export function subscribeConversation(projectId:string,conversationId:string,onChange:()=>void,onLive:(live:boolean)=>void) {
  let last:string|undefined;
  return onSnapshot(doc(database(),"projects",projectId,"conversations",conversationId),snapshot=>{
    onLive(true);
    const data=snapshot.data()||{};
    const key=JSON.stringify(Object.keys(data).filter(k=>!LEASE_FIELDS.has(k)).sort().map(k=>[k,data[k]]));
    if(last!==undefined&&key!==last)onChange();
    last=key;
  },()=>onLive(false));
}
// Runs at most once per interval and always runs after the final call of a burst.
export function throttle(run:()=>void,interval:number) {
  let timer:ReturnType<typeof setTimeout>|undefined,lastRun=0;
  const call=()=>{
    if(timer)return;
    timer=setTimeout(()=>{timer=undefined;lastRun=Date.now();run();},Math.max(0,interval-(Date.now()-lastRun)));
  };
  call.cancel=()=>{clearTimeout(timer);timer=undefined;};
  return call;
}
