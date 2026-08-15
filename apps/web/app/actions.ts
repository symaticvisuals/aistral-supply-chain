"use server"

import { revalidatePath } from "next/cache"

import { markHandled } from "@/lib/api"

export async function handleCase(formData: FormData) {
  const caseId = String(formData.get("case_id") ?? "").trim()
  const asOf = String(formData.get("as_of") ?? "").trim()
  const done = String(formData.get("done")) === "true"
  if (!caseId || !asOf) return
  await markHandled(caseId, asOf, done)
  revalidatePath("/")
}
