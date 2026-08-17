"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const payload = {
      email: String(form.get("email")),
      password: String(form.get("password")),
    };

    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      router.push("/login");
      return;
    }
    const data = await res.json().catch(() => ({}));
    setError(
      typeof data.detail === "string"
        ? data.detail
        : "Không tạo được tài khoản. Thử lại nhé.",
    );
    setBusy(false);
  }

  return (
    <main
      style={{ maxWidth: 380, margin: "80px auto", fontFamily: "system-ui" }}
    >
      <h1>Tạo tài khoản</h1>
      <form onSubmit={onSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          required
          style={{ width: "100%" }}
        />
        <label htmlFor="password">Mật khẩu</label>
        <input
          id="password"
          name="password"
          type="password"
          minLength={8}
          maxLength={128}
          required
          style={{ width: "100%" }}
        />
        <p style={{ fontSize: 13 }}>Ít nhất 8 ký tự.</p>
        {error && (
          <p role="alert" style={{ color: "#C8322E" }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Đang tạo…" : "Tạo tài khoản"}
        </button>
      </form>
      <p>
        Đã có tài khoản? <a href="/login">Đăng nhập</a>
      </p>
    </main>
  );
}
