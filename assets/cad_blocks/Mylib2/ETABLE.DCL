ETABLE : dialog {
       label = "QSV - Xu\U+1EA5t thu\U+1ED9c t\U+00EDnh c\U+00E1c \U+0111\U+1ED1i t\U+01B0\U+1EE3ng th\U+00E0nh Table";
       : column {
         : boxed_column {
           : popup_list { key = "entityType"; label = "Lo\U+1EA1i \U+0111\U+1ED1i t\U+01B0\U+1EE3ng:"; width = 25; value = "0"; }
         }
         : boxed_row {
           label = "Ch\U+1ECDn c\U+00E1c thu\U+1ED9c t\U+00EDnh c\U+1EA7n xu\U+1EA5t";
           : column {
             : toggle { key = "tog1";  label = "Name"; }
             : toggle { key = "tog2";  label = "Name Layer"; }
             : toggle { key = "tog3";  label = "Color"; }
             : toggle { key = "tog4";  label = "Point ID"; }
             : toggle { key = "tog5";  label = "Point ID"; }
             : toggle { key = "tog6";  label = "End Point ID"; }
             : toggle { key = "tog10"; label = "Line Type"; }
             : toggle { key = "tog16"; label = "Angle"; }
             : toggle { key = "tog17"; label = "Area"; }
             : toggle { key = "tog19"; label = "Handle"; }
           }
           : column {
             : toggle { key = "tog7";  label = "Tag"; }
             : toggle { key = "tog8";  label = "Contents"; }
             : toggle { key = "tog9";  label = "Style"; }
             : toggle { key = "tog11"; label = "Radius/Height"; }
             : toggle { key = "tog12"; label = "Diameter/Width"; }
             : toggle { key = "tog13"; label = "Vertex/Control Points"; }
             : toggle { key = "tog14"; label = "Major Axis"; }
             : toggle { key = "tog15"; label = "Minor Axis"; }
             : toggle { key = "tog18"; label = "Length/Perimeter"; }
           }
         }
         : row {
           : toggle { 
             key = "tog20"; 
             label = "Ch\U+1ECDn theo v\U+00F9ng";
           }  
         }          
         : boxed_column {
           : row {
             : toggle { 
               key = "labeltog"; 
               label = "\U+0110\U+1EB7t t\U+00EAn \U+0111i\U+1EC3m"; 
             }
             : popup_list { 
               key = "layerlist"; 
               label = "Thu\U+1ED9c Layer:"; 
               width = 25; 
               value = "0"; 
             }
           }
           : row {
             : edit_box {
               key = "lblprefix";
               label = "T\U+00EAn \U+0111i\U+1EC3m:";
               edit_width = 5;
               value = "";
             }
             : edit_box {
               key = "lblstrtnum";
               label = "S\U+1ED1 b\U+1EAFt \U+0111\U+1EA7u:";
               edit_width = 12;
               value = "1";
             }           
           }
         }
         : row {
           : boxed_row { 
             : button {
               key = "accept";
               label = "  Th\U+1EF1c hi\U+1EC7n  ";
               is_default = true;
             }
             : button {
               key = "cancel";
               label = "  Cancel  ";
               is_default = false;
               is_cancel = true;
             }
           }
         }
      }
}


