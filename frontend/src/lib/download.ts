import { apiDownload } from "./api";
import { prescriptionPdfPath } from "./endpoints";

export async function downloadPrescriptionPdf(
  token: string,
  prescriptionId: string,
): Promise<void> {
  const blob = await apiDownload(prescriptionPdfPath(prescriptionId), token);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `prescription-${prescriptionId}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
