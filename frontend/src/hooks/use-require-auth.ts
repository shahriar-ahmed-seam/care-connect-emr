"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { type Role, useAuthStore } from "@/lib/auth-store";

export function useRequireAuth(allowed?: Role[]) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    if (token === null) {
      router.replace("/login");
      return;
    }
    if (allowed && user && !allowed.includes(user.role)) {
      router.replace("/login");
    }
  }, [token, user, allowed, router]);

  return { token, user };
}
