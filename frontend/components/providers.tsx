"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ConfirmDialog } from "./confirm-dialog";
import { GlobalLoader } from "./global-loader";
export function Providers({children}:{children:React.ReactNode}) {
  const [client]=useState(()=>new QueryClient({defaultOptions:{queries:{retry:1,refetchOnWindowFocus:true}}}));
  return <QueryClientProvider client={client}>{children}<ConfirmDialog /><GlobalLoader /></QueryClientProvider>;
}
