# frontend/app.py
from flask import Flask, render_template_string

BACKEND_BASE_URL = "http://127.0.0.1:8000"
BACKEND_PROCESS_URL = f"{BACKEND_BASE_URL}/process"
BACKEND_RANGE_URL = f"{BACKEND_BASE_URL}/ranges"

app = Flask(__name__)

HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>EEG Prediction Exporter</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 40px; color: #222; }
      .container { max-width: 640px; margin: auto; }
      .card { border: 1px solid #ddd; border-radius: 8px; padding: 24px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
      label { display: block; margin-top: 16px; font-weight: 600; }
      input[type="number"], input[type="file"] { margin-top: 8px; width: 100%; }
      button { margin-top: 24px; padding: 12px 24px; font-size: 16px; border-radius: 4px; cursor: pointer; border: none; background-color: #2563eb; color: white; }
      button:disabled { opacity: 0.6; cursor: not-allowed; }
      #status { margin-top: 20px; font-weight: 500; }
      .progress-container { margin-top: 12px; width: 100%; background: #f3f4f6; border-radius: 6px; height: 18px; display: none; }
      .progress-bar { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #60a5fa); border-radius: 6px; color: #fff; font-size: 12px; text-align: center; line-height: 18px; transition: width 0.2s ease; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="card">
        <h1>EEG Prediction Exporter</h1>
        <p>Upload EDF recordings to generate an Excel file of the GRU-based Seizure Analysis.</p>
        <form
          id="prediction-form"
          action="{{ backend_process_url }}"
          method="post"
          enctype="multipart/form-data"
          target="download-frame"
        >
          <label>
            EDF Recording(s) (.edf)
            <input type="file" name="edf_files" accept=".edf" multiple required>
          </label>
          <label>
            Ground Truth Workbook (.xlsx, optional)
            <input type="file" name="gt_excel" accept=".xls,.xlsx">
          </label>
          <button type="button" id="load-range-btn">Load Available Time Range</button>
          <div id="range-info" style="margin-top:10px;"></div>
          <label>
            Analysis Start
            <input type="datetime-local" name="analysis_start" step="1" disabled>
          </label>
          <label>
            Analysis End
            <input type="datetime-local" name="analysis_end" step="1" disabled>
          </label>
          <label>
            Window Length
            <input type="number" name="window_length" min="1" value="1000" required>
          </label>
          <button type="submit" id="submit-btn">Generate Predictions</button>
        </form>
        <iframe name="download-frame" style="display:none;"></iframe>
        <div id="progress-container" class="progress-container">
          <div id="progress-bar" class="progress-bar">0%</div>
        </div>
        <div id="status"></div>
      </div>
    </div>

    <script>
      const RANGE_URL = "{{ backend_range_url }}";
      const PROCESS_URL = "{{ backend_process_url }}";

      document.addEventListener("DOMContentLoaded", () => {
        const form = document.getElementById("prediction-form");
        const status = document.getElementById("status");
        const submitBtn = document.getElementById("submit-btn");
        const edfInput = document.querySelector('input[name="edf_files"]');
        const startInput = document.querySelector('input[name="analysis_start"]');
        const endInput = document.querySelector('input[name="analysis_end"]');
        const rangeInfo = document.getElementById("range-info");
        const loadRangeBtn = document.getElementById("load-range-btn");
        const progressContainer = document.getElementById("progress-container");
        const progressBar = document.getElementById("progress-bar");

        function setProgress(percent) {
          progressContainer.style.display = "block";
          const safe = Math.max(0, Math.min(100, percent));
          progressBar.style.width = safe + "%";
          progressBar.textContent = `${safe.toFixed(0)}%`;
          if (safe >= 100) {
            setTimeout(() => {
              progressContainer.style.display = "none";
              progressBar.style.width = "0%";
              progressBar.textContent = "0%";
            }, 600);
          }
        }

        function resetAnalysisInputs() {
          startInput.value = "";
          endInput.value = "";
          startInput.disabled = true;
          endInput.disabled = true;
          startInput.removeAttribute("min");
          startInput.removeAttribute("max");
          endInput.removeAttribute("min");
          endInput.removeAttribute("max");
          rangeInfo.innerHTML = "";
        }

        edfInput.addEventListener("change", () => {
          resetAnalysisInputs();
        });

        loadRangeBtn.addEventListener("click", async () => {
          if (!edfInput || !edfInput.files || edfInput.files.length === 0) {
            status.textContent = "Please select at least one EDF file first.";
            return;
          }
          status.textContent = "Analyzing files to determine available time range...";
          loadRangeBtn.disabled = true;

          const formData = new FormData();
          for (const file of edfInput.files) {
            formData.append("edf_files", file, file.name);
          }

          try {
            const response = await fetch(RANGE_URL, {
              method: "POST",
              body: formData,
            });
            if (!response.ok) {
              const errText = await response.text();
              throw new Error(errText || "Failed to determine ranges.");
            }
            const data = await response.json();
            const { overall_start, overall_end, files } = data;
            if (overall_start) {
              startInput.min = overall_start;
              startInput.value = overall_start;
              endInput.min = overall_start;
            }
            if (overall_end) {
              startInput.max = overall_end;
              endInput.max = overall_end;
              endInput.value = overall_end;
            }
            startInput.disabled = false;
            endInput.disabled = false;
            rangeInfo.innerHTML = files
              .map(
                (file) =>
                  `<div><strong>${file.name}</strong>: ${file.start} → ${file.end}</div>`
              )
              .join("");
            status.textContent = "Select the desired analysis window.";
          } catch (err) {
            resetAnalysisInputs();
            status.textContent = `Error: ${err.message}`;
          } finally {
            loadRangeBtn.disabled = false;
          }
        });

        form.addEventListener("submit", (event) => {
          event.preventDefault();
          status.textContent = "";
          if (!edfInput || !edfInput.files || edfInput.files.length === 0) {
            status.textContent = "Please select at least one EDF file.";
            return;
          }

          if (startInput.value && endInput.value && startInput.value > endInput.value) {
            status.textContent = "Analysis start must be before the end time.";
            return;
          }

          const formData = new FormData();
          for (const file of edfInput.files) {
            formData.append("edf_files", file, file.name);
          }
          if (startInput.value) {
            formData.append("analysis_start", startInput.value);
          }
          if (endInput.value) {
            formData.append("analysis_end", endInput.value);
          }
          formData.append("window_length", form.window_length.value || 1000);
          if (form.gt_excel && form.gt_excel.files.length > 0) {
            formData.append("gt_excel", form.gt_excel.files[0], form.gt_excel.files[0].name);
          }

          status.textContent = "Uploading and running inference...";
          submitBtn.disabled = true;
          setProgress(5);

          fetch(PROCESS_URL, {
            method: "POST",
            body: formData,
          })
            .then(async (response) => {
              if (!response.ok) {
                const errText = await response.text();
                throw new Error(errText || "Backend error");
              }
              const total = Number(response.headers.get("Content-Length")) || null;
              const reader = response.body.getReader();
              const chunks = [];
              let received = 0;
              while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                chunks.push(value);
                received += value.length;
                if (total) {
                  setProgress(Math.min(99, (received / total) * 100));
                } else {
                  setProgress(Math.min(90, 5 + (received % 10000) / 100));
                }
              }
              setProgress(100);
              const blob = new Blob(chunks, {
                type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              });
              const disposition = response.headers.get("Content-Disposition") || "";
              const match = disposition.match(/filename="?(.+)"?/);
              const filename = match ? match[1] : "predictions.xlsx";
              const url = window.URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = filename;
              document.body.appendChild(link);
              link.click();
              link.remove();
              window.URL.revokeObjectURL(url);
              status.textContent = "Download complete.";
            })
            .catch((err) => {
              status.textContent = `Error: ${err.message}`;
              setProgress(0);
            })
            .finally(() => {
              submitBtn.disabled = false;
            });
        });
      });
    </script>
  </body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        HTML_TEMPLATE,
        backend_process_url=BACKEND_PROCESS_URL,
        backend_range_url=BACKEND_RANGE_URL,
    )


if __name__ == "__main__":
    app.run(debug=True, port=8050)
