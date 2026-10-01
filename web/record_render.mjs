import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const videoPath = '/Users/amirhossein/Documents/AI_render/docs/recordings/render_flow.webm';
const outputDir = path.dirname(videoPath);

// Ensure output directory exists
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

(async () => {
  const browser = await chromium.launch();

  // Context with video recording
  const context = await browser.newContext({
    recordVideo: {
      dir: outputDir,
      size: { width: 1280, height: 800 }
    }
  });

  const page = await context.newPage();

  try {
    console.log('Navigating to app...');
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle', timeout: 30000 }).catch(e => console.log('Navigation warning:', e.message));
    await page.waitForTimeout(2000);

    console.log('Looking for New Reel button...');
    const newReelButton = await page.$('button:has-text("New Reel")');
    if (newReelButton) {
      console.log('Clicking New Reel...');
      await newReelButton.click();
      await page.waitForTimeout(1500);
    }

    console.log('Waiting for file input...');
    const fileInput = await page.$('input[type="file"]');
    if (fileInput) {
      console.log('Uploading raw.mp4...');
      const videoFile = '/Users/amirhossein/Documents/AI_render/samples/media/raw.mp4';
      await fileInput.setInputFiles(videoFile);
      await page.waitForTimeout(2000);
    }

    // Check for second file input for plan
    const fileInputs = await page.$$('input[type="file"]');
    if (fileInputs.length > 1) {
      console.log('Uploading plan file...');
      const planFile = '/Users/amirhossein/Documents/AI_render/samples/plans/full.json';
      await fileInputs[1].setInputFiles(planFile);
      await page.waitForTimeout(1000);
    }

    console.log('Looking for Create button...');
    const createButton = await page.$('button:has-text("Create")');
    if (createButton) {
      console.log('Pressing Create...');
      await createButton.click();
      await page.waitForTimeout(3000);
    }

    console.log('Looking for Plan Review button...');
    const reviewButton = await page.$('button:has-text("Plan Review")');
    if (reviewButton) {
      console.log('Opening Plan Review...');
      await reviewButton.click();
      await page.waitForTimeout(4000);
    }

    console.log('Looking for Render button...');
    const renderButton = await page.$('button:has-text("Render")');
    if (renderButton) {
      console.log('Pressing Render...');
      await renderButton.click();
      await page.waitForTimeout(2000);
    }

    console.log('Waiting for render to complete...');
    // Wait for progress to reach 100% or video to play
    let complete = false;
    for (let i = 0; i < 240; i++) {  // Up to 4 minutes
      // Check for progress element
      const progressElements = await page.$$('[class*="progress"], [aria-label*="progress"]');
      for (const elem of progressElements) {
        const text = await elem.textContent();
        if (text && text.includes('100')) {
          console.log('Progress reached 100%');
          complete = true;
          break;
        }
      }

      // Check for video element
      const video = await page.$('video');
      if (video && !complete) {
        try {
          const duration = await page.evaluate(() => {
            const v = document.querySelector('video');
            return v ? v.duration : null;
          });

          const currentTime = await page.evaluate(() => {
            const v = document.querySelector('video');
            return v ? v.currentTime : null;
          });

          if (currentTime !== null && currentTime >= 5) {
            console.log(`Video playing: ${currentTime}s`);
            complete = true;
            break;
          }
        } catch (e) {
          // Ignore evaluation errors
        }
      }

      if (complete) break;
      await page.waitForTimeout(500);
    }

    if (complete) {
      console.log('Waiting 5 seconds for video playback...');
      await page.waitForTimeout(5000);
    }

    console.log('Recording complete, closing browser...');
  } catch (error) {
    console.error('Error during recording:', error);
  } finally {
    await context.close();
    await browser.close();
  }
})();
