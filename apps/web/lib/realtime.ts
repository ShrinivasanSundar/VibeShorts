import { getApp } from "firebase/app";
import { collection, connectFirestoreEmulator, getFirestore, onSnapshot } from "firebase/firestore";
let connected=false;
export function subscribeRunSummaries(projectId:string,onChange:()=>void) {
  const database=getFirestore(getApp());
  if(!connected&&process.env.NEXT_PUBLIC_MODE!=="production") {connectFirestoreEmulator(database,"127.0.0.1",8080);connected=true;}
  return onSnapshot(collection(database,"projects",projectId,"run_summaries"),onChange,()=>{/* Authenticated API polling remains the fallback. */});
}
