import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { BlogGeneratorComponent } from './blog-generator/blog-generator.component';

const routes: Routes = [
  {path: '', redirectTo: 'blog-generator', pathMatch: 'full'},
  {path:'blog-generator', component: BlogGeneratorComponent}

];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule]
})
export class AppRoutingModule { }
