"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError } from "../lib/api";
import { ConfirmDialog } from "./confirm-dialog";
import { GlobalLoader } from "./global-loader";
export function Providers({children}:{children:React.ReactNode}) {
  const [client]=useState(()=>new QueryClient({defaultOptions:{queries:{
    staleTime:60000, retry:(count,error)=>!(error instanceof ApiError && [401,403,429].includes(error.status)) && count<1,
    refetchOnWindowFocus:true, refetchIntervalInBackground:false,
  }}}));
  return <QueryClientProvider client={client}>{children}<ConfirmDialog /><GlobalLoader /></QueryClientProvider>;
}
