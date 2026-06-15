import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ProgressEvent {
  agent: string;
  message: string;
  status: string;
}

export interface PlanTask {
  id: number;
  title: string;
  goal: string;
  bullets: string[];
  target_words: number;
  section_type: string;
}

export interface BlogPlan {
  blog_title: string;
  audience: string;
  tone: string;
  tasks: PlanTask[];
}

export interface BlogResponse {
  topic: string;
  final: string;
  plan: BlogPlan | null;
  events: ProgressEvent[];
}

@Injectable({
  providedIn: 'root'
})
export class BlogService {
  private readonly baseUrl = '';
  constructor(private http: HttpClient) {}

  generateBlog(topic: string, correlationId: string): Observable<BlogResponse> {
    return this.http.post<BlogResponse>(`${environment.apiBaseUrl}/generate-blog`, { topic,correlationId });
  }

  connectToEvents(correlationId: string): EventSource {
    return new EventSource(`${environment.sseBaseUrl}/events/events/${correlationId}`)
  }
}
