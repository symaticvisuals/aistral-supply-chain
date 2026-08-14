import { Button } from "@workspace/ui/components/button"

export default function Page() {
  return (
    <main className="flex min-h-[100dvh] items-center justify-center p-6">
      <div className="flex max-w-md flex-col gap-3 text-sm">
        <h1 className="text-lg font-semibold tracking-tight">Kestrel</h1>
        <p className="text-muted-foreground">
          Next.js + FastAPI monorepo. Add components with shadcn and start
          building.
        </p>
        <Button className="w-fit">Button</Button>
        <p className="font-mono text-xs text-muted-foreground">
          Press d to toggle dark mode
        </p>
      </div>
    </main>
  )
}
