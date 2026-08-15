import { IBM_Plex_Mono, IBM_Plex_Sans, Teko } from "next/font/google"
import type { Metadata } from "next"

import "@workspace/ui/globals.css"
import { cn } from "@workspace/ui/lib/utils"

const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
})

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
})

// Condensed and headline-only. Teko is the loudest thing in the theme, so it
// never sets body copy — headings and figures, nothing else.
const display = Teko({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-display",
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
      className={cn(
        "antialiased",
        sans.variable,
        mono.variable,
        display.variable,
        "font-sans"
      )}
    >
      <body>{children}</body>
    </html>
  )
}
