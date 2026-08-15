import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@workspace/ui/lib/utils"

// Status chips. Uppercase survives here because they are one or two words,
// scanned rather than read, and caps make them findable in a dense table.
// Variants are operational states, not decoration.
const badgeVariants = cva(
  "group/badge inline-flex h-[18px] w-fit shrink-0 items-center justify-center gap-1 overflow-hidden border px-1.5 font-mono text-[9px] tracking-[0.1em] whitespace-nowrap uppercase transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring has-data-[icon=inline-end]:pr-1 has-data-[icon=inline-start]:pl-1 aria-invalid:border-destructive [&>svg]:pointer-events-none [&>svg]:size-2.5!",
  {
    variants: {
      variant: {
        default:
          "border-primary bg-primary text-primary-foreground [a]:hover:bg-primary/85",
        secondary:
          "border-border bg-secondary text-secondary-foreground [a]:hover:bg-accent",
        destructive:
          "border-destructive bg-transparent text-destructive [a]:hover:bg-destructive/10",
        outline: "border-current text-foreground [a]:hover:bg-accent",
        ok: "border-current bg-transparent text-ok",
        watch: "border-current bg-transparent text-watch",
        breach: "border-current bg-transparent text-breach",
        refused: "border-current bg-transparent text-refused",
        chilled: "border-current bg-transparent text-chilled",
        cases: "border-current bg-transparent text-cases",
        eaches: "border-current bg-transparent text-eaches",
        ghost: "border-transparent hover:bg-accent",
        link: "border-transparent text-cases underline-offset-4 hover:underline",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }
