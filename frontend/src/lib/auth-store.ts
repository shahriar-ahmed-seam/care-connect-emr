"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Role = "patient" | "doctor" | "admin";

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  status: string;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
  setAuth: (token: string, user: AuthUser) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setAuth: (token, user) => set({ token, user }),
      clear: () => set({ token: null, user: null }),
    }),
    { name: "cc_auth" },
  ),
);

export function dashboardPath(role: Role): string {
  switch (role) {
    case "patient":
      return "/p/dashboard";
    case "doctor":
      return "/d/dashboard";
    case "admin":
      return "/a/dashboard";
  }
}
