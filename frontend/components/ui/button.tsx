import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
const variants=cva("inline-flex items-center justify-center gap-2 rounded-md text-xs font-medium disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2",{variants:{variant:{default:"primary",secondary:"secondary",ghost:"bg-transparent"},size:{default:"px-3 py-2",icon:"size-8"}},defaultVariants:{variant:"default",size:"default"}});
export function Button({className,variant,size,asChild=false,...props}:React.ComponentProps<"button">&VariantProps<typeof variants>&{asChild?:boolean}) {
 const Component=asChild?Slot:"button";return <Component data-slot="button" className={twMerge(clsx(variants({variant,size}),className))} {...props}/>;
}
