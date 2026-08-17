import { NextResponse } from "next/server";
import { clearSessionCookies } from "@/lib/session";

export async function POST(request: Request) {
  const res = NextResponse.redirect(new URL("/login", request.url), 303);
  clearSessionCookies(res);
  return res;
}
