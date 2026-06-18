import { Component, OnDestroy } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { marked } from 'marked';
import { BlogPlan, BlogService, CompleteEvent, ProgressEvent, QualityAssessment } from './blog.service';
import { NgZone } from '@angular/core';

@Component({
  selector: 'app-blog-generator',
  templateUrl: './blog-generator.component.html',
  styleUrls: ['./blog-generator.component.scss']
})
export class BlogGeneratorComponent implements OnDestroy {
  readonly blogGeneratorform: FormGroup;

  loading = false;
  currentTopic = '';
  plan: BlogPlan | null = null;
  currentEvent: ProgressEvent | null = null;
  blogContentRaw = '';
  blogContent = '';
  errorMessage = '';
  copyLabel = 'Copy markdown';
  isStreamingComplete = false;
  isCompleted = false;
  qualityAssessment : QualityAssessment | null = null;
  elapsedSeconds = 0;
  timerId : any;

  private streamTimers: number[] = [];
  private eventSource: EventSource | null = null;

  constructor(private fb: FormBuilder,private blogService: BlogService, private ngZone : NgZone) {
    this.blogGeneratorform = this.fb.group({
      topic: ['', [Validators.required, Validators.pattern(/\S+/)]]
    });
  }

  generateBlog(): void {
    if (this.blogGeneratorform.invalid) {
      this.blogGeneratorform.markAllAsTouched();
      return;
    }

    this.elapsedSeconds = 0;
    this.timerId = setInterval(() => {
      this.elapsedSeconds++;
    }, 1000);

    const topic = this.blogGeneratorform.value.topic.trim();
    this.resetGeneration(topic);
    this.loading = true;

    //generates new correlation id from frontend and passes to backend
    const correlationId = crypto.randomUUID();
    this.eventSource = this.blogService.connectToEvents(correlationId);

    this.eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data) as ProgressEvent | CompleteEvent;

      console.log('SSE Event', data);

      this.ngZone.run(() => {
        if ('type' in data && data.type === 'COMPLETE') {

          this.isCompleted = true;
          this.closeEventSource();
          clearInterval(this.timerId);
          return;
      }
      this.currentEvent = data as ProgressEvent;
      });
    };

    this.eventSource.onerror = () => {
      this.closeEventSource();
    };

    this.blogService.generateBlog(topic, correlationId).subscribe({
      next: (response) => {
        this.currentTopic = response.topic;
        this.plan = response.plan;
        this.loading = false;
        this.qualityAssessment = response.quality_assessment ?? null;
        this.streamBlog(response.final);
      },
      error: () => {
        this.closeEventSource();
        this.loading = false;
        this.errorMessage = 'The workflow could not complete. Check that the backend is running and try again.';
      }
    });
  }

  copyToClipboard(): void {
    if (!this.blogContentRaw) {
      return;
    }

    if (navigator.clipboard) {
      navigator.clipboard.writeText(this.blogContentRaw).then(() => this.showCopySuccess());
      return;
    }

    const temp = document.createElement('textarea');
    temp.value = this.blogContentRaw;
    document.body.appendChild(temp);
    temp.select();
    document.execCommand('copy');
    document.body.removeChild(temp);
    this.showCopySuccess();
  }

  downloadMarkdown(): void {
    if (!this.blogContentRaw) {
      return;
    }

    const blob = new Blob([this.blogContentRaw], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${this.slugify(this.currentTopic) || 'generated-blog'}.md`;
    link.click();
    URL.revokeObjectURL(url);
  }

  ngOnDestroy(): void {
    this.clearStreamTimers();
    this.closeEventSource();
  }

  private resetGeneration(topic: string): void {
    this.clearStreamTimers();
    this.closeEventSource();
    this.currentTopic = topic;
    this.plan = null;
    this.currentEvent = null;
    this.blogContentRaw = '';
    this.blogContent = '';
    this.errorMessage = '';
    this.copyLabel = 'Copy markdown';
    this.isStreamingComplete = false;
    this.isCompleted = false;
  }

  private streamBlog(content: string): void {
    this.clearStreamTimers();
    this.blogContentRaw = content;
    const words = content.split(' ');
    let current = '';

    words.forEach((word, index) => {
      const timer = window.setTimeout(() => {
        current += `${word} `;
        this.blogContent = marked.parse(current) as string;
        if (index === words.length - 1) {
          this.isStreamingComplete = true;
        }
      }, index * 5);
      this.streamTimers.push(timer);
    });
  }

  private clearStreamTimers(): void {
    this.streamTimers.forEach((timer) => window.clearTimeout(timer));
    this.streamTimers = [];
  }

  private closeEventSource(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  private showCopySuccess(): void {
    this.copyLabel = 'Copied';
    window.setTimeout(() => {
      this.copyLabel = 'Copy markdown';
    }, 1600);
  }

  private slugify(value: string): string {
    return value
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '');
  }

}
