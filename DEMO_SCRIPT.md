# Matrix Vision: demo video script (about 80 seconds)

Record on a phone, or Chrome device mode at 390 px. Use only the synthetic files in `samples/`: print them, or show
them on a second screen and photograph that. Sign in before recording.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00–0:08 | A hand holding the printed `samples/lab_report.jpg`, looking confused. | "In Nepal, a patient often walks out of a lab with a report in English medical shorthand, and no one to explain it." |
| 0:08–0:15 | The Matrix Vision home page in Nepali. Tap **फोटो खिच्नुहोस्**. | "Matrix Vision is a companion to Matrix, our hospital directory. Take a photo, and it explains the paper in simple Nepali." |
| 0:15–0:27 | Take the photo, pick **Bhaktapur**, tap **बुझाइदिनुहोस्**. The scanning animation shows "SAM 3…", then "Muse Spark…". | "Meta's SAM 3 finds the paper in the photo, and the film on an X-ray, so Muse Spark gets a sharp close-up. Muse Spark reads it and returns strict, structured JSON." |
| 0:27–0:40 | The result: "५ वटा नतिजा सामान्यभन्दा फरक", with Haemoglobin and blood sugar marked. Tap **सुनाउनुहोस्**. | "Out-of-range results come first. The flags are checked in code against the printed range, not taken on the model's word. Listen to it read aloud in Nepali." |
| 0:40–0:50 | Tap **बोलेर सोध्नुहोस्** and ask in Nepali: "हेमोग्लोबिन कम भनेको के हो?". Show "हामीले बुझेको प्रश्न" and the answer. | "Ask a follow-up question by voice. Muse Voice transcribes it, and Muse Spark answers only from this document, never with a diagnosis or a dose change." |
| 0:50–1:00 | Scroll to the department and the hospital card. Tap **Matrix मा हेर्नुहोस्**; the Matrix hospital page opens. | "It suggests the department and lists hospitals from Matrix's directory. The model can't invent hospitals: any name not on Matrix's list is removed in code." |
| 1:00–1:12 | New scan with `samples/lab_report_critical.jpg`. The red banner appears with **१०२ मा फोन गर्नुहोस्**. | "Safety isn't left to the AI. Matrix's danger-sign rules and critical lab values run in plain code, so a potassium of 6.9 shows 'Call 102' whatever the model says. Danger signs in the patient's own note are caught even when the model is down." |
| 1:12–1:20 | Tap **PDF डाउनलोड**; show the Nepali PDF. End on the logo and URL. | "Download a Nepali summary to take to the doctor. Your photo is never stored. Matrix Vision, at matrixvision.hospitalsofnepal.com." |

On-screen text at the end: *Built with Meta Muse Spark · SAM 3 · Muse Voice. Explains documents only. Not a diagnosis.*

**Before recording:**
- Set `META_API_KEY` and do one dry run of each sample. Model output varies, so pick the take where the Nepali reads
  most naturally.
- The phone needs a Nepali or Hindi text-to-speech voice installed for the read-aloud shot. On Android, install
  "Speech Services by Google" and download Nepali.
- Don't show a real report, a real patient's name or a real API key on screen.
