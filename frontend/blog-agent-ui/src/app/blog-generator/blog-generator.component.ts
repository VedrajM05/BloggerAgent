import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { marked } from 'marked';

@Component({
  selector: 'app-blog-generator',
  templateUrl: './blog-generator.component.html',
  styleUrls: ['./blog-generator.component.scss']
})
export class BlogGeneratorComponent implements OnInit {

  blogGeneratorform: FormGroup;
  loading = false;
  blogContentRaw = '';
  blogContent = '';
  publishedUrl = 'https://dev.to/vedraj_mokashi/exploring-rag-embedding-techniques-in-depth-1005';
  isStreamingComplete = false;
  currentTopic = '';
  showPublishBadge = false;
  displayedPublishUrl = '';
  // @ViewChild('scrollContainer') scrollContainer!: ElementRef

  constructor(private fb: FormBuilder, private http: HttpClient) {

    this.blogGeneratorform = this.fb.group({
      topic: ['', [Validators.required, Validators.pattern(/\S+/)]]
    })
  }


  ngOnInit(): void {
    this.readStaticFile();
  }

  generateBlog() {
    console.log("Blog generator called...");

    if (this.blogGeneratorform.invalid) {
      return;
    }

    this.loading = true;
    const topic = this.blogGeneratorform.value.topic;
    console.log(topic);
    this.currentTopic = this.blogGeneratorform.value.topic;
    this.http.post<any>('http://127.0.0.1:8000/api/v1/generate-blog', { topic })
      .subscribe({
        next: (res) => {
          this.blogContentRaw = res.final;
          this.streamBlog(res.final)
          this.loading = false;
          console.log(this.blogContent);
        },
        error: () => {
          this.loading = false;
        }
      })
  }

  readStaticFile() {
    this.http.get("assets/exploring the uses of langsmith in 2026.md", { responseType: 'text' })
      .subscribe({
        next: (res) => {
          // this.blogContent = marked.parse(res) as string;
          this.blogContentRaw = res;
          this.streamBlog(res)
          //console.log(data);

        }
      })
  }

  streamBlog(content: string) {

    this.showPublishBadge = false;
    this.displayedPublishUrl = '';

    // Split content into words, "Hello world from Angular" ==> ["Hello", "world", "from", "Angular"]
    const words = content.split(" ");

    let current = "";
    this.blogContent = "";
    this.isStreamingComplete = false;

    words.forEach((word, index) => {
      // Delay each word using setTimeout
      setTimeout(() => {

        //Delay each word using setTimeout, Keeps adding words one by one
        current += word + " ";

        //Convert to HTML using markdown
        this.blogContent = marked.parse(current) as string;

        //Force DOM Update
        //this.cdr.detectChanges();


        //calling auto scroll logic
        //this.scrollToBottom();

        if (index === words.length - 1) {
          this.isStreamingComplete = true
          if (this.publishedUrl) {
            this.streamPublishBadge(); //  NOW THIS EXISTS
          }
        }

      }, index * 10); // speed control
    });
  }

  copyToClipboard() {
    const temp = document.createElement('textarea');
    temp.value = this.blogContentRaw; // IMPORTANT: store raw markdown separately
    document.body.appendChild(temp);
    temp.select();
    document.execCommand('copy');
    document.body.removeChild(temp);

    alert("Copied to clipboard!");
  }

  streamPublishBadge() {
    this.showPublishBadge = true;

    const url = this.publishedUrl;
    let current = '';

    const chars = url.split('');

    chars.forEach((char, index) => {
      setTimeout(() => {
        current += char;
        this.displayedPublishUrl = current;
      }, index * 15); // speed of URL typing
    });
  }

  // scrollToBottom() {
  //   try {
  //     const element = this.scrollContainer.nativeElement;

  //     // DEBUG LOG HERE
  //     console.log("scrollHeight:", element.scrollHeight);
  //     console.log("scrollTop:", element.scrollTop);

  //     element.scrollTo({
  //       top: element.scrollHeight,
  //       behavior: 'auto'
  //     });
  //   }
  //   catch (err) {
  //     console.error();
  //   }
  // }


  // =========================== Validations ===========================

  // getTopicControl(){
  //   //console.log(this.blogGeneratorform.get('topic'));
  //   return this.blogGeneratorform.get('topic');
  // }

  // isTopicInvalid() : boolean{
  //   debugger;
  //   const control = this.getTopicControl();
  //   console.log("input is : ",control?.value);

  //   if(control?.value == '' || control?.value == null){
  //     return true; 
  //   }
  //   else{
  //     return false;
  //   }
  // }

}
