import { NextResponse } from "next/server";
import { callBackend } from "@/lib/backend";

export async function POST(request: Request) {
  const body = await request.text();
  const upstream = await callBackend("/api/auth/register", {
    method: "POST",
    body,
  });
  return NextResponse.json(await upstream.json(), { status: upstream.status });
}
