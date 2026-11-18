chiadat :dialog {label = "QSV - Chia di\U+1EC7n t\U+00EDch";
spacer;
:text {key= "tong";alignment= centered;}
spacer;
:boxed_row {label= "Ki\U+1EC3u chia";
    :column{children_fixed_width = true;
        :radio_button {label="Theo dien tich               "; key = "theodt"; value = 1;}
        :radio_button {label="Theo ty le                      "; key = "theotl";}
    }
    :column{
        :edit_box {key = "dientich"; width = 20; fixed_width= true;}
        :edit_box {key = "tyle"; width = 20; fixed_width= true;}
    }
}
spacer; spacer;
:popup_list {label= "\U+0110\U+1ED9 ch\U+00EDnh x\U+00E1c"; key= "chinhxac"; width = 40; fixed_width= true;alignment= right;}
spacer; spacer;
:radio_row {label = "Ki\U+1EC3u di chuy\U+1EC3n \U+0111\U+01B0\U+1EDDng chia";
    :radio_button {label = "Song song"; key = "song"; value = 1;}
    :radio_button {label = "Quay quanh 1 diem"; key = "quay";}
    spacer;
}
spacer; spacer;
:row {
:toggle {label = "Ghi di\U+1EC7n t\U+00EDch sau khi chia"; key= "ghi";}
:edit_box {key = "caochu"; label = "Cao ch\U+1EEF ghi KQ";width = 20; fixed_width= true;}
}
spacer; spacer;
:text{ label= "CH\U+00DA \U+00DD"; alignment= centered;}
:text{ label= "B\U+1EA5m OK, \U+0110\U+01B0\U+1EDDng chia s\U+1EBD di chuy\U+1EC3n v\U+1EC1 \U+0111\U+00FAng di\U+1EC7n t\U+00EDch. H\U+00E3y ch\U+1EDD gi\U+00E2y l\U+00E1t..."; alignment= centered;}
spacer; spacer;
ok_cancel;
spacer; spacer;
:text{ label= "Ch\U+00FAc b\U+1EA1n l\U+00E0m vi\U+1EC7c vui v\U+1EBB"; alignment= centered;}
}
