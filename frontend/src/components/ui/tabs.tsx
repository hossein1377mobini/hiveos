import * as TabsPrimitive from "@radix-ui/react-tabs";
import { forwardRef, type ComponentProps } from "react";
import { cn } from "../../lib/utils";

// HiveOS Tabs (underline variant) — mockup §۱۷ (.tabs/.tab with count chips).
const Tabs = TabsPrimitive.Root;

const TabsList = forwardRef<HTMLDivElement, ComponentProps<typeof TabsPrimitive.List>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.List
      ref={ref}
      className={cn("flex gap-1 border-b border-neutral-200", className)}
      {...props}
    />
  ),
);
TabsList.displayName = "TabsList";

const TabsTrigger = forwardRef<HTMLButtonElement, ComponentProps<typeof TabsPrimitive.Trigger>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "-mb-px cursor-pointer border-b-2 border-transparent px-4 py-2.5 text-[13.5px] font-bold text-neutral-600 transition-colors",
        "hover:text-neutral-900",
        "data-[state=active]:border-navy-600 data-[state=active]:text-navy-600",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-200",
        className,
      )}
      {...props}
    />
  ),
);
TabsTrigger.displayName = "TabsTrigger";

const TabsContent = forwardRef<HTMLDivElement, ComponentProps<typeof TabsPrimitive.Content>>(
  ({ className, ...props }, ref) => (
    <TabsPrimitive.Content
      ref={ref}
      className={cn("mt-4 focus-visible:outline-none", className)}
      {...props}
    />
  ),
);
TabsContent.displayName = "TabsContent";

export { Tabs, TabsList, TabsTrigger, TabsContent };