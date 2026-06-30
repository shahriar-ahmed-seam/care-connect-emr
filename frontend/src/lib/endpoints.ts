import { apiFetch } from "./api";
import type { AuthUser, Role } from "./auth-store";

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AuthUser;
}

export function register(input: {
  email: string;
  password: string;
  full_name: string;
  role: "patient" | "doctor";
}) {
  return apiFetch<{ user: AuthUser }>("/auth/register", {
    method: "POST",
    body: input,
  });
}

export function login(input: { email: string; password: string }) {
  return apiFetch<LoginResult>("/auth/login", { method: "POST", body: input });
}

export function requestPasswordReset(email: string) {
  return apiFetch<{ message: string }>("/auth/password-reset/request", {
    method: "POST",
    body: { email },
  });
}

export function logout(token: string) {
  return apiFetch<{ message: string }>("/auth/logout", {
    method: "POST",
    token,
  });
}

export interface AppointmentSummary {
  id: string;
  doctor_id: string;
  patient_id: string;
  doctor_name: string;
  patient_name: string;
  start_time: string;
  end_time: string;
  status: string;
  can_join: boolean;
}

export interface PrescriptionView {
  id: string;
  doctor_name: string;
  patient_name: string;
  issued_at: string;
  pdf_status: string;
  medications: { id: string; name: string; dosage: string; frequency: string; duration: string }[];
}

export interface VitalsView {
  id: string;
  recorded_at: string;
  blood_pressure: number | null;
  heart_rate: number | null;
  temperature: number | null;
  weight: number | null;
}

export function patientDashboard(token: string) {
  return apiFetch<{
    upcoming_appointments: AppointmentSummary[];
    recent_prescriptions: PrescriptionView[];
    vitals: VitalsView[];
  }>("/patient/dashboard", { token });
}

export function doctorDashboard(token: string) {
  return apiFetch<{ today_appointments: AppointmentSummary[]; pending_today: number }>(
    "/doctor/dashboard",
    { token },
  );
}

export function adminDashboard(token: string) {
  return apiFetch<{
    total_patients: number;
    active_doctors: number;
    appointments_today: number;
  }>("/admin/dashboard", { token });
}

export interface UserRow {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  status: string;
}

export function adminUsers(token: string) {
  return apiFetch<{ users: UserRow[] }>("/admin/users", { token });
}

export function pendingApprovals(token: string) {
  return apiFetch<{ accounts: UserRow[] }>("/admin/accounts/pending", { token });
}

export function approveDoctor(token: string, id: string) {
  return apiFetch(`/admin/doctors/${id}/approve`, { method: "POST", token });
}

export function rejectDoctor(token: string, id: string) {
  return apiFetch(`/admin/doctors/${id}/reject`, { method: "POST", token });
}

export function deactivateUser(token: string, id: string) {
  return apiFetch(`/admin/accounts/${id}/deactivate`, { method: "POST", token });
}

// --- Doctor search & booking ------------------------------------------------
export interface DoctorResult {
  id: string;
  full_name: string;
  specialty: string;
  qualifications: string | null;
  consultation_fee_bdt: string;
}

export function searchDoctors(token: string, specialty: string) {
  return apiFetch<{ doctors: DoctorResult[] }>(
    `/doctors?specialty=${encodeURIComponent(specialty)}`,
    { token },
  );
}

export interface SlotView {
  id: string;
  date: string;
  start_time: string;
  end_time: string;
  status: string;
}

export function doctorSlots(token: string, doctorId: string) {
  return apiFetch<{ slots: SlotView[] }>(`/doctors/${doctorId}/slots`, { token });
}

export function bookAppointment(token: string, slotId: string) {
  return apiFetch<AppointmentSummary>("/appointments", {
    method: "POST",
    token,
    body: { slot_id: slotId },
  });
}

export function cancelAppointment(token: string, id: string) {
  return apiFetch(`/appointments/${id}/cancel`, { method: "POST", token });
}

// --- Doctor profile & slot management ---------------------------------------
export interface DoctorProfileView {
  specialty: string;
  qualifications: string | null;
  consultation_fee_bdt: string;
}

export function getMyProfile(token: string) {
  return apiFetch<DoctorProfileView>("/doctors/me/profile", { token });
}

export function saveMyProfile(
  token: string,
  input: { specialty: string; qualifications?: string | null; consultation_fee_bdt: number },
) {
  return apiFetch<DoctorProfileView>("/doctors/me/profile", {
    method: "PUT",
    token,
    body: input,
  });
}

export function createSlot(
  token: string,
  input: { date: string; start_time: string; end_time: string },
) {
  return apiFetch<SlotView>("/doctors/me/slots", {
    method: "POST",
    token,
    body: input,
  });
}

export function deleteSlot(token: string, slotId: string) {
  return apiFetch(`/doctors/me/slots/${slotId}`, { method: "DELETE", token });
}

// --- Clinical records (EMR) -------------------------------------------------
export interface PatientRecord {
  medical_history: { id: string; description: string; entry_date: string; created_at: string }[];
  vitals: VitalsView[];
  diagnoses: { id: string; text: string; recorded_date: string }[];
  prescriptions: PrescriptionView[];
}

export function getPatientRecord(token: string, patientId: string) {
  return apiFetch<PatientRecord>(`/patients/${patientId}/record`, { token });
}

export function recordVitals(
  token: string,
  patientId: string,
  input: {
    appointment_id: string;
    blood_pressure?: number | null;
    heart_rate?: number | null;
    temperature?: number | null;
    weight?: number | null;
  },
) {
  return apiFetch(`/patients/${patientId}/vitals`, {
    method: "POST",
    token,
    body: input,
  });
}

export function recordDiagnosis(
  token: string,
  appointmentId: string,
  input: { text: string; recorded_date: string },
) {
  return apiFetch(`/appointments/${appointmentId}/diagnosis`, {
    method: "POST",
    token,
    body: input,
  });
}

export interface MedicationInput {
  name: string;
  dosage: string;
  frequency: string;
  duration: string;
}

export function createPrescription(
  token: string,
  appointmentId: string,
  medications: MedicationInput[],
) {
  return apiFetch<PrescriptionView>(`/appointments/${appointmentId}/prescription`, {
    method: "POST",
    token,
    body: { medications },
  });
}

/** Build the PDF download URL for a prescription (auth via fetch in apiDownload). */
export function prescriptionPdfPath(prescriptionId: string) {
  return `/prescriptions/${prescriptionId}/pdf`;
}
