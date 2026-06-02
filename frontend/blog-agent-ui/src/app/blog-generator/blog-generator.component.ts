import { Component, OnDestroy } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { marked } from 'marked';
import { BlogPlan, BlogService, PlanTask, ProgressEvent } from './blog.service';

@Component({
  selector: 'app-blog-generator',
  templateUrl: './blog-generator.component.html',
  styleUrls: ['./blog-generator.component.scss']
})
export class BlogGeneratorComponent implements OnDestroy {
  readonly blogGeneratorform: FormGroup;
  readonly loadingMessages = [
    'Research Agent working...',
    'Research Analyst extracting insights...',
    'Planning Agent preparing tasks...',
    'Writer Agents generating content...',
    'Editor Agent assembling the final article...'
  ];

  loading = false;
  currentTopic = '';
  plan: BlogPlan | null = null;
  events: ProgressEvent[] = [];
  visibleEvents: ProgressEvent[] = [];
  blogContentRaw = '';
  blogContent = '';
  errorMessage = '';
  copyLabel = 'Copy markdown';
  isStreamingComplete = false;
  traceComplete = false;
  loadingStep = 0;

  private loadingTimer?: number;
  private streamTimers: number[] = [];
  private eventTimers: number[] = [];

  constructor(
    private fb: FormBuilder,
    private blogService: BlogService
  ) {
    this.blogGeneratorform = this.fb.group({
      topic: ['', [Validators.required, Validators.pattern(/\S+/)]]
    });
  }

  get activeLoadingMessage(): string {
    return this.loadingMessages[Math.min(this.loadingStep, this.loadingMessages.length - 1)];
  }

  get planTasks(): PlanTask[] {
    return this.plan?.tasks ?? [];
  }

  get activeEventIndex(): number {
    return this.traceComplete ? -1 : this.visibleEvents.length - 1;
  }

  generateBlog(): void {
    if (this.blogGeneratorform.invalid) {
      this.blogGeneratorform.markAllAsTouched();
      return;
    }

    const topic = this.blogGeneratorform.value.topic.trim();
    this.resetGeneration(topic);
    this.loading = true;
    this.startLoadingProgress();

    this.blogService.generateBlog(topic).subscribe({
      next: (response) => {
        this.stopLoadingProgress();
        this.currentTopic = response.topic;
        this.plan = response.plan;
        this.events = response.events ?? [];
        this.loading = false;
        this.revealEvents(this.events);
        this.streamBlog(response.final);
      },
      error: () => {
        this.stopLoadingProgress();
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

  trackByTaskId(_: number, task: PlanTask): number {
    return task.id;
  }

  trackByEventIndex(index: number): number {
    return index;
  }

  ngOnDestroy(): void {
    this.stopLoadingProgress();
    this.clearStreamTimers();
    this.clearEventTimers();
  }

  private resetGeneration(topic: string): void {
    this.stopLoadingProgress();
    this.clearStreamTimers();
    this.clearEventTimers();
    this.currentTopic = topic;
    this.plan = null;
    this.events = [];
    this.visibleEvents = [];
    this.blogContentRaw = '';
    this.blogContent = '';
    this.errorMessage = '';
    this.copyLabel = 'Copy markdown';
    this.isStreamingComplete = false;
    this.traceComplete = false;
    this.loadingStep = 0;
  }

  private startLoadingProgress(): void {
    this.loadingTimer = window.setInterval(() => {
      if (this.loadingStep < this.loadingMessages.length - 1) {
        this.loadingStep += 1;
      }
    }, 1400);
  }

  private stopLoadingProgress(): void {
    if (this.loadingTimer !== undefined) {
      window.clearInterval(this.loadingTimer);
      this.loadingTimer = undefined;
    }
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

  private revealEvents(events: ProgressEvent[]): void {
    this.clearEventTimers();
    this.visibleEvents = [];
    this.traceComplete = false;

    events.forEach((event, index) => {
      const timer = window.setTimeout(() => {
        this.visibleEvents = [...this.visibleEvents, event];
        if (index === events.length - 1) {
          const completeTimer = window.setTimeout(() => {
            this.traceComplete = true;
          }, 700);
          this.eventTimers.push(completeTimer);
        }
      }, index * 650);
      this.eventTimers.push(timer);
    });

    if (!events.length) {
      this.traceComplete = true;
    }
  }

  private clearEventTimers(): void {
    this.eventTimers.forEach((timer) => window.clearTimeout(timer));
    this.eventTimers = [];
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
