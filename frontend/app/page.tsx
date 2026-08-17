import { redirect } from "next/navigation";
import { getAccessToken } from "@/lib/session";

export default async function HomePage() {
  const token = await getAccessToken();
  redirect(token ? "/dashboard" : "/login");
}
