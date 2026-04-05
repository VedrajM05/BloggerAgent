import { HttpClient } from '@angular/common/http';
import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { marked } from 'marked';

@Component({
  selector: 'app-blog-generator',
  templateUrl: './blog-generator.component.html',
  styleUrls: ['./blog-generator.component.scss']
})
export class BlogGeneratorComponent  {

  blogGeneratorform : FormGroup;
  loading = false;
  blogContent = '';

  constructor(private fb : FormBuilder, private http : HttpClient) { 

    this.blogGeneratorform = this.fb.group({
      topic : []
    })
  }

  generateBlog(){
    
    this.loading = true;

    const topic = this.blogGeneratorform.value.topic;
    console.log(topic);

    this.http.post<any>('http://127.0.0.1:8000/api/v1/generate-blog', {topic})
      .subscribe({
        next: (res) => {
          this.blogContent = marked.parse(res.final) as string;
          this.loading = false;
          console.log(this.blogContent);
        },
        error: () => {
          this.loading = false;
        }
      })


  }

}
