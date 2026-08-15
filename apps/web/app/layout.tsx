import { Source_Sans_3 } from "next/font/google"
import type { Metadata } from "next"

import "@workspace/ui/globals.css"
import { cn } from "@workspace/ui/lib/utils"

// One face for the whole morning brief. A second family (especially a mono)
// made this look like a developer console. Tabular figures live in this face.
const sans = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-sans",
})

export const metadata: Metadata = {
  title: "Kestrel Control Tower",
  description: "What happened yesterday: where service failed, where cash leaked.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={cn("antialiased", sans.variable, "font-sans")}
    >
      <body>{children}</body>
    </html>
  )
}
